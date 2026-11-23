from __future__ import annotations

import argparse
from importlib import metadata
from importlib.util import find_spec
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import dedent
from textwrap import indent
from time import perf_counter
from typing import TypedDict


try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]


WORKLOADS = {
    "noop": "pass",
    "busy": "for _ in range({iterations}):\n    pass",
    "mixed": "if case % 10 == 0:\n    for _ in range({iterations}):\n        pass",
}

# Measure CPU inside the pytest process so it excludes xdist workers.
PYTEST_RUNNER = dedent("""\
    import sys
    from time import process_time

    start = process_time()
    import pytest

    exit_code = pytest.main(sys.argv[1:])
    print(process_time() - start)
    sys.exit(exit_code)
    """)


class Sample(TypedDict):
    workload: str
    workers: int
    repetition: int
    wall_seconds: float
    controller_cpu_seconds: float
    total_cpu_seconds: float | None


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def worker_count(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative worker count")
    return number


def write_workload(directory: Path, workload: str, tests: int, iterations: int) -> None:
    directory.mkdir()
    (directory / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    body = WORKLOADS[workload].format(iterations=iterations)
    (directory / "test_fast.py").write_text(
        "import pytest\n\n\n"
        f'@pytest.mark.parametrize("case", range({tests}))\n'
        "def test_fast(case):\n"
        f"{indent(body, '    ')}\n",
        encoding="utf-8",
    )


def children_cpu() -> float | None:
    if resource is None:
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def run_sample(
    directory: Path,
    env: dict[str, str],
    workload: str,
    workers: int,
    repetition: int,
) -> Sample:
    command = [
        sys.executable,
        "-c",
        PYTEST_RUNNER,
        "-q",
        "--color=no",
        "-c",
        "pytest.ini",
        "-p",
        "xdist.plugin",
        "-p",
        "no:cacheprovider",
        "-n",
        str(workers),
        "--dist=load",
        "test_fast.py",
    ]
    cpu_before = children_cpu()
    start = perf_counter()
    result = subprocess.run(
        command, cwd=directory, env=env, capture_output=True, text=True, check=False
    )
    wall = perf_counter() - start
    cpu_after = children_cpu()
    if result.returncode:
        sys.exit(
            f"{workload} with -n {workers} failed (exit {result.returncode})\n"
            f"{result.stdout}{result.stderr}"
        )

    return {
        "workload": workload,
        "workers": workers,
        "repetition": repetition,
        "wall_seconds": wall,
        "controller_cpu_seconds": float(result.stdout.splitlines()[-1]),
        "total_cpu_seconds": (
            cpu_after - cpu_before
            if cpu_before is not None and cpu_after is not None
            else None
        ),
    }


def summarize(values: list[float | None]) -> dict[str, float] | None:
    measured = [value for value in values if value is not None]
    if not measured:
        return None
    return {
        "median": statistics.median(measured),
        "min": min(measured),
        "max": max(measured),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark pytest-xdist on fast tests."
    )
    parser.add_argument(
        "--workloads", nargs="+", choices=WORKLOADS, default=list(WORKLOADS)
    )
    parser.add_argument("--workers", nargs="+", type=worker_count, default=[0, 1, 2, 4])
    parser.add_argument(
        "--tests", type=positive_int, default=3000, help="tests per workload"
    )
    parser.add_argument("--busy-iterations", type=positive_int, default=40000)
    parser.add_argument("--repeats", type=positive_int, default=5)
    parser.add_argument(
        "--seed", type=int, default=1428, help="seed for shuffling each round"
    )
    parser.add_argument(
        "--label", help="optional revision or variant label for the JSON output"
    )
    args = parser.parse_args()
    if len(args.workers) != len(set(args.workers)) or len(args.workloads) != len(
        set(args.workloads)
    ):
        parser.error("specify each worker count and workload once")

    try:
        versions = {
            name: metadata.version(name)
            for name in ("pytest", "pytest-xdist", "execnet")
        }
    except metadata.PackageNotFoundError as error:
        parser.error(f"use a Python environment with {error.name} installed")
    xdist = find_spec("xdist")
    env = os.environ.copy()
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DEBUG"):
        env.pop(name, None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = os.pathsep.join(
            os.path.abspath(path) for path in env["PYTHONPATH"].split(os.pathsep)
        )

    cases = [
        (workload, workers) for workload in args.workloads for workers in args.workers
    ]
    rng = random.Random(args.seed)
    samples = []
    with TemporaryDirectory(prefix="xdist-fast-tests-") as temp:
        root = Path(temp)
        for workload in args.workloads:
            write_workload(root / workload, workload, args.tests, args.busy_iterations)
        for repetition in range(1, args.repeats + 1):
            order = cases.copy()
            rng.shuffle(order)
            for workload, workers in order:
                samples.append(
                    run_sample(root / workload, env, workload, workers, repetition)
                )

    summary = []
    for workload, workers in cases:
        group = [
            sample
            for sample in samples
            if (sample["workload"], sample["workers"]) == (workload, workers)
        ]
        summary.append(
            {
                "workload": workload,
                "workers": workers,
                "wall_seconds": summarize([sample["wall_seconds"] for sample in group]),
                "controller_cpu_seconds": summarize(
                    [sample["controller_cpu_seconds"] for sample in group]
                ),
                "total_cpu_seconds": summarize(
                    [sample["total_cpu_seconds"] for sample in group]
                ),
            }
        )

    print(
        json.dumps(
            {
                "configuration": vars(args),
                "environment": {
                    "executable": sys.executable,
                    "python": sys.version,
                    "platform": platform.platform(),
                    "logical_cpus": os.cpu_count(),
                    "versions": versions,
                    "xdist_source": xdist.origin if xdist else None,
                },
                "samples": samples,
                "summary": summary,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

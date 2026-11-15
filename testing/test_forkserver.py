from __future__ import annotations

import multiprocessing
import os
import signal
import sys
import time

import execnet
import pytest

from xdist._forkserver import _validate_spec
from xdist._forkserver import start_forkserver


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires Unix fork")
@pytest.mark.parametrize("method", ["popen", "forkserver", "ini", "override"])
def test_import_snapshot_and_worker_lifecycle(
    pytester: pytest.Pytester, method: str
) -> None:
    pytester.makepyfile(
        preloaded="""
            import os
            import_pid = os.getpid()
            configured_pid = None
        """,
    )
    pytester.makeconftest(
        r"""
        import os
        import preloaded
        import pytest

        with open("conftest_imports", "a") as imports:
            imports.write(f"{os.getpid()}\n")

        def pytest_addoption(parser):
            parser.addoption("--application-option", type=int)

        def pytest_configure(config):
            assert config.getoption("application_option") == 42
            preloaded.configured_pid = os.getpid()

        def pytest_configure_node(node):
            node.workerinput["controller_import_pid"] = preloaded.import_pid

        @pytest.fixture(scope="session")
        def fixture_pid():
            return os.getpid()
        """
    )
    pytester.makepyfile(
        test_workers=f"""
            import os
            import multiprocessing
            import threading
            import preloaded
            import pytest

            collection_pid = os.getpid()

            @pytest.mark.parametrize("case", range(8))
            def test_worker(case, fixture_pid, request):
                assert (preloaded.import_pid == os.getpid()) is {method in ("popen", "override")!r}
                if {method in ("forkserver", "ini")!r}:
                    assert preloaded.import_pid == os.getppid()
                    assert preloaded.import_pid == request.config.workerinput["controller_import_pid"]
                    assert multiprocessing.get_start_method() == "forkserver"
                assert preloaded.configured_pid == os.getpid()
                assert collection_pid == os.getpid()
                assert fixture_pid == os.getpid()
                assert threading.current_thread() is threading.main_thread()
        """
    )
    args = ["-n2", "--application-option=42"]
    if method in ("ini", "override"):
        pytester.makeini("[pytest]\nxdist_worker_start_method = forkserver")
        if method == "override":
            args.append("--worker-start-method=popen")
    elif method == "forkserver":
        args.append("--worker-start-method=forkserver")
    result = pytester.runpytest_subprocess(*args, timeout=30)
    result.assert_outcomes(passed=8)
    assert result.stdout.str().count("test session starts") == 1
    imports = (pytester.path / "conftest_imports").read_text().splitlines()
    assert len(imports) == (1 if method in ("forkserver", "ini") else 3)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires Unix fork")
def test_replacement_worker_uses_snapshot(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        preloaded="""
            import os
            import_pid = os.getpid()
        """
    )
    pytester.makeconftest("import preloaded")
    pytester.makepyfile(
        """
        import os
        import preloaded

        def test_crash():
            os._exit(1)

        def test_after_crash():
            assert preloaded.import_pid != os.getpid()

        def test_remaining():
            assert preloaded.import_pid != os.getpid()
        """
    )
    result = pytester.runpytest_subprocess(
        "-n1", "--worker-start-method=forkserver", "--max-worker-restart=1", timeout=30
    )
    result.assert_outcomes(failed=1, passed=2)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires Unix fork")
@pytest.mark.parametrize("stop_thread", [False, True])
def test_import_threads_and_preparation_hook(
    pytester: pytest.Pytester, stop_thread: bool
) -> None:
    pytester.makeconftest(
        f"""
        import threading
        stop = threading.Event()
        thread = threading.Thread(target=stop.wait, daemon=True)
        thread.start()

        def pytest_xdist_before_fork(config):
            if {stop_thread!r}:
                stop.set()
                thread.join()

        def pytest_unconfigure(config):
            stop.set()
            thread.join()
        """
    )
    pytester.makepyfile("def test_pass(): pass")
    result = pytester.runpytest_subprocess(
        "-n1", "--worker-start-method=forkserver", timeout=30
    )
    if stop_thread:
        result.assert_outcomes(passed=1)
    else:
        assert result.ret == pytest.ExitCode.USAGE_ERROR
        result.stderr.fnmatch_lines(["*require single-threaded imports*"])


@pytest.mark.parametrize("args", [("-n0",), ("-n2", "--collect-only")])
def test_non_distributed_runs_do_not_fork(
    pytester: pytest.Pytester, args: tuple[str, ...]
) -> None:
    pytester.makeini("[pytest]\nxdist_worker_start_method = forkserver")
    pytester.makeconftest(
        """
        def pytest_xdist_before_fork(config):
            raise AssertionError("must not fork")
        """
    )
    pytester.makepyfile("def test_pass(): pass")
    result = pytester.runpytest_subprocess(*args, timeout=30)
    assert result.ret == pytest.ExitCode.OK


def test_platform_without_fork(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = pytester.parseconfig()
    monkeypatch.setattr(multiprocessing, "get_all_start_methods", lambda: ["spawn"])
    with pytest.raises(pytest.UsageError, match="require Unix forkserver support"):
        start_forkserver(config)


@pytest.mark.parametrize(
    "spec",
    [
        "ssh=host",
        f"popen//python={sys.executable}",
        "popen//env:EXAMPLE=value",
        "popen//execmodel=thread",
    ],
)
def test_unsupported_worker_settings(spec: str) -> None:
    with pytest.raises(pytest.UsageError, match="requires local popen workers"):
        _validate_spec(execnet.XSpec(spec))


def test_invalid_start_method(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nxdist_worker_start_method = invalid")
    result = pytester.runpytest_subprocess(timeout=30)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*Unknown xdist worker start method: 'invalid'*"])


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires Unix forkserver")
def test_threaded_launcher_and_existing_forkserver(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        existing_preload=r"""
            import os
            with open("existing_preloads", "a") as log:
                log.write(f"{os.getpid()}\n")
        """,
        runner="""
            import multiprocessing
            import threading
            import pytest

            def child():
                pass

            if __name__ == "__main__":
                multiprocessing.set_start_method("spawn")
                multiprocessing.set_forkserver_preload(["existing_preload"])
                context = multiprocessing.get_context("forkserver")
                stop = threading.Event()
                thread = threading.Thread(target=stop.wait)
                thread.start()
                try:
                    for _ in range(2):
                        process = context.Process(target=child)
                        process.start()
                        process.join()
                        assert process.exitcode == 0
                        process.close()
                        result = pytest.main([
                            "-n1", "--worker-start-method=forkserver", "-q"
                        ])
                        assert result == 0
                        assert multiprocessing.get_start_method() == "spawn"
                finally:
                    stop.set()
                    thread.join()
        """,
    )
    pytester.makeconftest(
        r"""
        import os
        with open("conftest_imports", "a") as log:
            log.write(f"{os.getpid()}\n")
        """
    )
    pytester.makepyfile("def test_pass(): pass")
    result = pytester.run(sys.executable, "runner.py", timeout=30)
    assert result.ret == 0
    assert len((pytester.path / "existing_preloads").read_text().splitlines()) == 1
    assert len((pytester.path / "conftest_imports").read_text().splitlines()) == 2


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires Unix forkserver")
@pytest.mark.parametrize("crash", [None, "controller", "launcher"])
def test_session_processes_are_cleaned_up(
    pytester: pytest.Pytester, crash: str | None
) -> None:
    pytester.makeconftest(
        r"""
        import multiprocessing
        import os

        with open("processes", "a") as log:
            log.write(f"{os.getpid()}\n")

        def pytest_configure(config):
            with open("processes", "a") as log:
                log.write(f"{os.getpid()}\n")
                log.write(f"{multiprocessing.parent_process().pid}\n")

        def pytest_configure_node(node):
            node.workerinput["controller_pid"] = os.getpid()
        """
    )
    pytester.makepyfile(
        runner="""
            import os
            import pytest
            if __name__ == "__main__":
                os.environ["LAUNCHER_PID"] = str(os.getpid())
                raise SystemExit(pytest.main([
                    "-n1", "--worker-start-method=forkserver"
                ]))
        """,
        test_worker=f"""
        import os
        import signal
        import time

        def test_worker(request):
            if {crash!r} is not None:
                pid = (
                    request.config.workerinput["controller_pid"]
                    if {crash!r} == "controller"
                    else int(os.environ["LAUNCHER_PID"])
                )
                os.kill(pid, signal.SIGKILL)
                time.sleep(30)
        """,
    )
    result = pytester.run(sys.executable, "runner.py", timeout=20)
    if crash == "controller":
        assert result.ret == pytest.ExitCode.INTERNAL_ERROR
    elif crash == "launcher":
        assert result.ret == -signal.SIGKILL
    else:
        result.assert_outcomes(passed=1)
    pids = {
        int(line) for line in (pytester.path / "processes").read_text().splitlines()
    }
    assert len(pids) == 4  # forkserver, helper, controller, worker
    deadline = time.monotonic() + 10
    while pids and time.monotonic() < deadline:
        for pid in list(pids):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pids.remove(pid)
        if pids:
            time.sleep(0.01)
    assert not pids, f"session processes still running: {pids}"


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires Unix forkserver")
def test_preload_error_is_reported(pytester: pytest.Pytester) -> None:
    pytester.makeconftest("raise RuntimeError('application preload failed')")
    pytester.makepyfile("def test_pass(): pass")
    result = pytester.runpytest_subprocess(
        "-n1", "--worker-start-method=forkserver", timeout=20
    )
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*RuntimeError: application preload failed*"])


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires Unix forkserver")
def test_launcher_forwards_interrupt(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        runner="""
            import os
            import signal
            import pytest
            if __name__ == "__main__":
                signal.signal(signal.SIGINT, signal.default_int_handler)
                os.environ["LAUNCHER_PID"] = str(os.getpid())
                raise SystemExit(pytest.main([
                    "-n1", "--worker-start-method=forkserver"
                ]))
        """
    )
    pytester.makepyfile(
        """
        import os
        import signal
        import time
        def test_interrupt():
            os.kill(int(os.environ["LAUNCHER_PID"]), signal.SIGINT)
            time.sleep(30)
        """
    )
    result = pytester.run(sys.executable, "runner.py", timeout=20)
    assert result.ret == pytest.ExitCode.INTERRUPTED
    result.stdout.fnmatch_lines(["*KeyboardInterrupt*"])

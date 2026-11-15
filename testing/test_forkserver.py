from __future__ import annotations

import os
import sys

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
        """
        import os
        import preloaded
        import pytest

        def pytest_configure(config):
            preloaded.configured_pid = os.getpid()

        @pytest.fixture(scope="session")
        def fixture_pid():
            return os.getpid()
        """
    )
    pytester.makepyfile(
        test_workers=f"""
            import os
            import threading
            import preloaded
            import pytest

            collection_pid = os.getpid()

            @pytest.mark.parametrize("case", range(8))
            def test_worker(case, fixture_pid):
                assert (preloaded.import_pid == os.getpid()) is {method in ("popen", "override")!r}
                assert preloaded.configured_pid == os.getpid()
                assert collection_pid == os.getpid()
                assert fixture_pid == os.getpid()
                assert threading.current_thread() is threading.main_thread()
        """
    )
    args = ["-n2"]
    if method in ("ini", "override"):
        pytester.makeini("[pytest]\nxdist_worker_start_method = forkserver")
        if method == "override":
            args.append("--worker-start-method=popen")
    elif method == "forkserver":
        args.append("--worker-start-method=forkserver")
    result = pytester.runpytest_subprocess(*args, timeout=30)
    result.assert_outcomes(passed=8)


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
    monkeypatch.delattr(os, "fork", raising=False)
    with pytest.raises(pytest.UsageError, match="require Unix fork support"):
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

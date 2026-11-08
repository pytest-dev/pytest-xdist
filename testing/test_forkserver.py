from __future__ import annotations

import sys

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform not in ("linux", "darwin"), reason="requires Unix fork and sockets"
)


@pytest.fixture(autouse=True)
def require_psutil() -> None:
    pytest.importorskip("psutil")


@pytest.mark.parametrize(
    "dist", ["load", "loadscope", "loadfile", "loadgroup", "worksteal", "each"]
)
def test_inherited_conftest(pytester: pytest.Pytester, dist: str) -> None:
    pytester.makeconftest("""
        import os
        import threading
        import pytest
        IMPORT_PID = os.getpid()
        RUN_UID = os.environ.get("PYTEST_XDIST_TESTRUNUID")
        @pytest.fixture(scope='session')
        def inherited(worker_id, tmp_path_factory):
            assert IMPORT_PID != os.getpid()
            assert RUN_UID == os.environ["PYTEST_XDIST_TESTRUNUID"]
            assert os.environ['PYTEST_XDIST_WORKER'] == worker_id
            assert 'PYTEST_XDIST_PRELOAD' not in os.environ
            assert threading.current_thread() is threading.main_thread()
            return tmp_path_factory.mktemp(worker_id)
    """)
    pytester.makepyfile("""
        import pytest
        @pytest.mark.parametrize('i', range(8))
        def test_ok(inherited, i):
            assert inherited.is_dir()
            print('captured output')
    """)
    result = pytester.runpytest_subprocess(
        "-n2", "--worker-start-method=forkserver", f"--dist={dist}", timeout=30
    )
    result.assert_outcomes(passed=16 if dist == "each" else 8)


def test_restart(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
        import os
        import pytest
        @pytest.mark.parametrize('i', range(8))
        def test_crash(i):
            if os.environ['PYTEST_XDIST_WORKER'] == 'gw0':
                os._exit(17)
    """)
    result = pytester.runpytest_subprocess(
        "-n2", "--worker-start-method=forkserver", timeout=30
    )
    result.assert_outcomes(passed=7, failed=1)
    result.stdout.fnmatch_lines(["*replacing crashed worker*"])


def test_preload_threads_rejected(pytester: pytest.Pytester) -> None:
    pytester.makeconftest("""
        import os
        if os.environ.get('PYTEST_XDIST_PRELOAD'):
            import threading
            threading.Thread(target=threading.Event().wait, daemon=True).start()
    """)
    pytester.makepyfile("def test_ok(): pass")
    result = pytester.runpytest_subprocess(
        "-n2", "--worker-start-method=forkserver", timeout=30
    )
    assert result.ret != 0
    result.stderr.fnmatch_lines(["*preload started background threads*"])


def test_preload_import_error(pytester: pytest.Pytester) -> None:
    pytester.makeconftest("""
        import os
        if os.environ.get('PYTEST_XDIST_PRELOAD'):
            raise RuntimeError('preload failed intentionally')
    """)
    pytester.makepyfile("def test_ok(): pass")
    result = pytester.runpytest_subprocess(
        "-n2", "--worker-start-method=forkserver", timeout=30
    )
    assert result.ret != 0
    result.stderr.fnmatch_lines(["*preload failed intentionally*"])


def test_cleanup_on_setup_failure(pytester: pytest.Pytester) -> None:
    psutil = pytest.importorskip("psutil")
    pidfile = pytester.path / "seed.pid"
    pytester.makeconftest(f"""
        import os
        from pathlib import Path
        if os.environ.get('PYTEST_XDIST_PRELOAD'):
            Path({str(pidfile)!r}).write_text(str(os.getpid()))
        def pytest_xdist_newgateway(gateway):
            raise RuntimeError('gateway setup failed intentionally')
    """)
    pytester.makepyfile("def test_ok(): pass")
    result = pytester.runpytest_subprocess(
        "-n2", "--worker-start-method=forkserver", timeout=30
    )
    assert result.ret != 0
    assert not psutil.pid_exists(int(pidfile.read_text()))


def test_coverage(pytester: pytest.Pytester) -> None:
    pytest.importorskip("pytest_cov")
    pytester.makepyfile(
        application="""
        def double(value):
            return value * 2
        """,
        test_app="""
        from application import double
        def test_double():
            assert double(3) == 6
        """,
    )
    result = pytester.runpytest_subprocess(
        "-n2",
        "--worker-start-method=forkserver",
        "-p",
        "pytest_cov",
        "--cov=application",
        "--cov-report=term",
        timeout=30,
    )
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*application.py*100%*"])


@pytest.mark.parametrize("start_method", ["popen", "forkserver"])
@pytest.mark.parametrize("test_fails", [False, True])
def test_worker_exit_handlers(
    pytester: pytest.Pytester, start_method: str, test_fails: bool
) -> None:
    pytester.makeconftest("""
        import atexit
        import os
        import sys
        from pathlib import Path

        def record_import_exit():
            worker = os.environ.get('PYTEST_XDIST_WORKER')
            if worker:
                with Path(f'exit-{worker}').open('a') as stream:
                    stream.write('import exit\\n')

        atexit.register(record_import_exit)

        def pytest_configure(config):
            if hasattr(config, 'workerinput'):
                def record_plugin_exit():
                    worker = config.workerinput['workerid']
                    with Path(f'exit-{worker}').open('a') as stream:
                        stream.write('plugin exit\\n')
                    sys.stderr.write('worker exit flush')
                atexit.register(record_plugin_exit)
    """)
    pytester.makepyfile(f"""
        import atexit
        from pathlib import Path
        def test_exit(worker_id):
            stream = Path(f'buffered-{{worker_id}}').open('w')
            stream.write('buffered data')
            atexit.register(stream.close)
            assert {not test_fails!r}
    """)
    result = pytester.runpytest_subprocess(
        "-n2", "--dist=each", f"--worker-start-method={start_method}", timeout=30
    )
    result.assert_outcomes(**{"failed" if test_fails else "passed": 2})
    assert "\n".join(result.errlines).count("worker exit flush") == 2
    for worker in ("gw0", "gw1"):
        assert (pytester.path / f"exit-{worker}").read_text().splitlines() == [
            "plugin exit",
            "import exit",
        ]
        assert (pytester.path / f"buffered-{worker}").read_text() == "buffered data"


def test_abrupt_exit_skips_exit_handlers(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
        import atexit
        import os
        from pathlib import Path
        def test_crash():
            atexit.register(Path('unexpected-exit-handler').touch)
            os._exit(17)
    """)
    result = pytester.runpytest_subprocess(
        "-n1", "--worker-start-method=forkserver", "--max-worker-restart=0", timeout=30
    )
    result.assert_outcomes(failed=1)
    assert not (pytester.path / "unexpected-exit-handler").exists()

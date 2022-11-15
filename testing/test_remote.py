import pprint
import pytest
import sys
import uuid

from xdist.workermanage import WorkerController
import execnet
import marshal

from queue import Queue

WAIT_TIMEOUT = 10.0


def check_marshallable(d):
    try:
        marshal.dumps(d)
    except ValueError:
        pprint.pprint(d)
        raise ValueError("not marshallable")


class EventCall:
    def __init__(self, eventcall):
        self.name, self.kwargs = eventcall

    def __str__(self):
        return f"<EventCall {self.name}(**{self.kwargs})>"


class WorkerSetup:
    def __init__(self, request, pytester: pytest.Pytester) -> None:
        self.request = request
        self.pytester = pytester
        self.use_callback = False
        self.events = Queue()  # type: ignore[var-annotated]

    def setup(self) -> None:
        self.pytester.chdir()
        # import os ; os.environ['EXECNET_DEBUG'] = "2"
        self.gateway = execnet.makegateway()
        self.config = config = self.pytester.parseconfigure()
        putevent = self.events.put if self.use_callback else None

        class DummyMananger:
            testrunuid = uuid.uuid4().hex
            specs = [0, 1]

        self.slp = WorkerController(DummyMananger, self.gateway, config, putevent)
        self.request.addfinalizer(self.slp.ensure_teardown)
        self.slp.setup()

    def popevent(self, name=None):
        while 1:
            if self.use_callback:
                data = self.events.get(timeout=WAIT_TIMEOUT)
            else:
                data = self.slp.channel.receive(timeout=WAIT_TIMEOUT)
            ev = EventCall(data)
            if name is None or ev.name == name:
                return ev
            print(f"skipping {ev}")

    def sendcommand(self, name, **kwargs):
        self.slp.sendcommand(name, **kwargs)


@pytest.fixture
def worker(request, pytester: pytest.Pytester) -> WorkerSetup:
    return WorkerSetup(request, pytester)


@pytest.mark.xfail(reason="#59")
def test_remoteinitconfig(pytester: pytest.Pytester) -> None:
    from xdist.remote import remote_initconfig

    config1 = pytester.parseconfig()
    config2 = remote_initconfig(config1.option.__dict__, config1.args)
    assert config2.option.__dict__ == config1.option.__dict__
    assert config2.pluginmanager.getplugin("terminal") in (-1, None)


class TestWorkerInteractor:
    @pytest.fixture
    def unserialize_report(self, pytestconfig):
        def unserialize(data):
            return pytestconfig.hook.pytest_report_from_serializable(
                config=pytestconfig, data=data
            )

        return unserialize

    def test_basic_collect_and_runtests(
        self, worker: WorkerSetup, unserialize_report
    ) -> None:
        worker.pytester.makepyfile(
            """
            def test_func():
                pass
        """
        )
        worker.setup()
        ev = worker.popevent()
        assert ev.name == "workerready"
        ev = worker.popevent()
        assert ev.name == "collectionstart"
        assert not ev.kwargs
        ev = worker.popevent("collectionfinish")
        assert ev.kwargs["topdir"] == str(worker.pytester.path)
        ids = ev.kwargs["ids"]
        assert len(ids) == 1
        worker.sendcommand("runtests", indices=list(range(len(ids))))
        worker.sendcommand("shutdown")
        ev = worker.popevent("logstart")
        assert ev.kwargs["nodeid"].endswith("test_func")
        assert len(ev.kwargs["location"]) == 3
        ev = worker.popevent("testreport")  # setup
        ev = worker.popevent("testreport")
        assert ev.name == "testreport"
        rep = unserialize_report(ev.kwargs["data"])
        assert rep.nodeid.endswith("::test_func")
        assert rep.passed
        assert rep.when == "call"
        ev = worker.popevent("workerfinished")
        assert "workeroutput" in ev.kwargs

    def test_remote_collect_skip(self, worker: WorkerSetup, unserialize_report) -> None:
        worker.pytester.makepyfile(
            """
            import pytest
            pytest.skip("hello", allow_module_level=True)
        """
        )
        worker.setup()
        ev = worker.popevent("collectionstart")
        assert not ev.kwargs
        ev = worker.popevent()
        assert ev.name == "collectreport"
        rep = unserialize_report(ev.kwargs["data"])
        assert rep.skipped
        assert rep.longrepr[2] == "Skipped: hello"
        ev = worker.popevent("collectionfinish")
        assert not ev.kwargs["ids"]

    def test_remote_collect_fail(self, worker: WorkerSetup, unserialize_report) -> None:
        worker.pytester.makepyfile("""aasd qwe""")
        worker.setup()
        ev = worker.popevent("collectionstart")
        assert not ev.kwargs
        ev = worker.popevent()
        assert ev.name == "collectreport"
        rep = unserialize_report(ev.kwargs["data"])
        assert rep.failed
        ev = worker.popevent("collectionfinish")
        assert not ev.kwargs["ids"]

    def test_runtests_all(self, worker: WorkerSetup, unserialize_report) -> None:
        worker.pytester.makepyfile(
            """
            def test_func(): pass
            def test_func2(): pass
        """
        )
        worker.setup()
        ev = worker.popevent()
        assert ev.name == "workerready"
        ev = worker.popevent()
        assert ev.name == "collectionstart"
        assert not ev.kwargs
        ev = worker.popevent("collectionfinish")
        ids = ev.kwargs["ids"]
        assert len(ids) == 2
        worker.sendcommand("runtests_all")
        worker.sendcommand("shutdown")
        for func in "::test_func", "::test_func2":
            for i in range(3):  # setup/call/teardown
                ev = worker.popevent("testreport")
                assert ev.name == "testreport"
                rep = unserialize_report(ev.kwargs["data"])
                assert rep.nodeid.endswith(func)
        ev = worker.popevent("workerfinished")
        assert "workeroutput" in ev.kwargs

    def test_happy_run_events_converted(
        self, pytester: pytest.Pytester, worker: WorkerSetup
    ) -> None:
        pytest.xfail("implement a simple test for event production")
        assert not worker.use_callback  # type: ignore[unreachable]
        worker.pytester.makepyfile(
            """
            def test_func():
                pass
        """
        )
        worker.setup()
        hookrec = pytester.getreportrecorder(worker.config)
        for data in worker.slp.channel:
            worker.slp.process_from_remote(data)
        worker.slp.process_from_remote(worker.slp.ENDMARK)
        pprint.pprint(hookrec.hookrecorder.calls)
        hookrec.hookrecorder.contains(
            [
                ("pytest_collectstart", "collector.fspath == aaa"),
                ("pytest_pycollect_makeitem", "name == 'test_func'"),
                ("pytest_collectreport", "report.collector.fspath == aaa"),
                ("pytest_collectstart", "collector.fspath == bbb"),
                ("pytest_pycollect_makeitem", "name == 'test_func'"),
                ("pytest_collectreport", "report.collector.fspath == bbb"),
            ]
        )

    def test_process_from_remote_error_handling(
        self, worker: WorkerSetup, capsys: pytest.CaptureFixture[str]
    ) -> None:
        worker.use_callback = True
        worker.setup()
        worker.slp.process_from_remote(("<nonono>", ()))
        out, err = capsys.readouterr()
        assert "INTERNALERROR> ValueError: unknown event: <nonono>" in out
        ev = worker.popevent()
        assert ev.name == "errordown"


def test_remote_env_vars(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import os
        def test():
            assert len(os.environ['PYTEST_XDIST_TESTRUNUID']) == 32
            assert os.environ['PYTEST_XDIST_WORKER'] in ('gw0', 'gw1')
            assert os.environ['PYTEST_XDIST_WORKER_COUNT'] == '2'
    """
    )
    result = pytester.runpytest("-n2", "--max-worker-restart=0")
    assert result.ret == 0


def test_remote_inner_argv(pytester: pytest.Pytester) -> None:
    """Test/document the behavior due to execnet using `python -c`."""
    pytester.makepyfile(
        """
        import sys

        def test_argv():
            assert sys.argv == ["-c"]
        """
    )
    result = pytester.runpytest("-n1")
    assert result.ret == 0


def test_remote_mainargv(pytester: pytest.Pytester) -> None:
    outer_argv = sys.argv

    pytester.makepyfile(
        """
        def test_mainargv(request):
            assert request.config.workerinput["mainargv"] == {!r}
        """.format(
            outer_argv
        )
    )
    result = pytester.runpytest("-n1")
    assert result.ret == 0


def test_remote_usage_prog(pytester: pytest.Pytester, request) -> None:
    if not hasattr(request.config._parser, "prog"):
        pytest.skip("prog not available in config parser")
    pytester.makeconftest(
        """
        import pytest

        config_parser = None

        @pytest.fixture
        def get_config_parser():
            return config_parser

        def pytest_configure(config):
            global config_parser
            config_parser = config._parser
    """
    )
    pytester.makepyfile(
        """
        import sys

        def test(get_config_parser, request):
            get_config_parser._getparser().error("my_usage_error")
    """
    )

    result = pytester.runpytest_subprocess("-n1")
    assert result.ret == 1
    result.stdout.fnmatch_lines(["*usage: *", "*error: my_usage_error"])


def test_remote_sys_path(pytester: pytest.Pytester) -> None:
    """Work around sys.path differences due to execnet using `python -c`."""
    pytester.makepyfile(
        """
        import sys

        def test_sys_path():
            assert "" not in sys.path
        """
    )
    result = pytester.runpytest("-n1")
    assert result.ret == 0

import py
import pprint
import pytest
import sys

from xdist.workermanage import WorkerController
import execnet
import marshal

from six.moves.queue import Queue

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
        return "<EventCall %s(**%s)>" % (self.name, self.kwargs)


class WorkerSetup:
    use_callback = False

    def __init__(self, request, testdir):
        self.request = request
        self.testdir = testdir
        self.events = Queue()

    def setup(self,):
        self.testdir.chdir()
        # import os ; os.environ['EXECNET_DEBUG'] = "2"
        self.gateway = execnet.makegateway()
        self.config = config = self.testdir.parseconfigure()
        putevent = self.use_callback and self.events.put or None

        class DummyMananger:
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
            print("skipping %s" % (ev,))

    def sendcommand(self, name, **kwargs):
        self.slp.sendcommand(name, **kwargs)


@pytest.fixture
def worker(request, testdir):
    return WorkerSetup(request, testdir)


@pytest.mark.xfail(reason="#59")
def test_remoteinitconfig(testdir):
    from xdist.remote import remote_initconfig

    config1 = testdir.parseconfig()
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

    def test_basic_collect_and_runtests(self, worker, unserialize_report):
        worker.testdir.makepyfile(
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
        assert ev.kwargs["topdir"] == worker.testdir.tmpdir
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

    def test_remote_collect_skip(self, worker, unserialize_report):
        worker.testdir.makepyfile(
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

    def test_remote_collect_fail(self, worker, unserialize_report):
        worker.testdir.makepyfile("""aasd qwe""")
        worker.setup()
        ev = worker.popevent("collectionstart")
        assert not ev.kwargs
        ev = worker.popevent()
        assert ev.name == "collectreport"
        rep = unserialize_report(ev.kwargs["data"])
        assert rep.failed
        ev = worker.popevent("collectionfinish")
        assert not ev.kwargs["ids"]

    def test_runtests_all(self, worker, unserialize_report):
        worker.testdir.makepyfile(
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

    def test_happy_run_events_converted(self, testdir, worker):
        py.test.xfail("implement a simple test for event production")
        assert not worker.use_callback
        worker.testdir.makepyfile(
            """
            def test_func():
                pass
        """
        )
        worker.setup()
        hookrec = testdir.getreportrecorder(worker.config)
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

    def test_process_from_remote_error_handling(self, worker, capsys):
        worker.use_callback = True
        worker.setup()
        worker.slp.process_from_remote(("<nonono>", ()))
        out, err = capsys.readouterr()
        assert "INTERNALERROR> ValueError: unknown event: <nonono>" in out
        ev = worker.popevent()
        assert ev.name == "errordown"


def test_remote_env_vars(testdir):
    testdir.makepyfile(
        """
        import os
        def test():
            assert os.environ['PYTEST_XDIST_WORKER'] in ('gw0', 'gw1')
            assert os.environ['PYTEST_XDIST_WORKER_COUNT'] == '2'
    """
    )
    result = testdir.runpytest("-n2", "--max-worker-restart=0")
    assert result.ret == 0


def test_remote_inner_argv(testdir):
    """Test/document the behavior due to execnet using `python -c`."""
    testdir.makepyfile(
        """
        import sys

        def test_argv():
            assert sys.argv == ["-c"]
        """
    )
    result = testdir.runpytest("-n1")
    assert result.ret == 0


def test_remote_mainargv(testdir):
    outer_argv = sys.argv

    testdir.makepyfile(
        """
        def test_mainargv(request):
            assert request.config.workerinput["mainargv"] == {!r}
        """.format(
            outer_argv
        )
    )
    result = testdir.runpytest("-n1")
    assert result.ret == 0


def test_remote_usage_prog(testdir, request):
    if not hasattr(request.config._parser, "prog"):
        pytest.skip("prog not available in config parser")
    testdir.makeconftest(
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
    testdir.makepyfile(
        """
        import sys

        def test(get_config_parser, request):
            get_config_parser._getparser().error("my_usage_error")
    """
    )

    result = testdir.runpytest_subprocess("-n1")
    assert result.ret == 1
    result.stdout.fnmatch_lines(["*usage: *", "*error: my_usage_error"])

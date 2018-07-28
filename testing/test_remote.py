import py
import pprint
import pytest
from xdist.workermanage import WorkerController, unserialize_report
from xdist.remote import serialize_report
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


class TestReportSerialization:
    def test_xdist_longrepr_to_str_issue_241(self, testdir):
        testdir.makepyfile(
            """
            import os
            def test_a(): assert False
            def test_b(): pass
        """
        )
        testdir.makeconftest(
            """
            def pytest_runtest_logreport(report):
                print(report.longrepr)
        """
        )
        res = testdir.runpytest("-n1", "-s")
        res.stdout.fnmatch_lines(["*1 failed, 1 passed *"])

    def test_xdist_report_longrepr_reprcrash_130(self, testdir):
        reprec = testdir.inline_runsource(
            """
                    import py
                    def test_fail(): assert False, 'Expected Message'
                """
        )
        reports = reprec.getreports("pytest_runtest_logreport")
        assert len(reports) == 3
        rep = reports[1]
        added_section = ("Failure Metadata", str("metadata metadata"), "*")
        rep.longrepr.sections.append(added_section)
        d = serialize_report(rep)
        check_marshallable(d)
        a = unserialize_report("testreport", d)
        # Check assembled == rep
        assert a.__dict__.keys() == rep.__dict__.keys()
        for key in rep.__dict__.keys():
            if key != "longrepr":
                assert getattr(a, key) == getattr(rep, key)
        assert rep.longrepr.reprcrash.lineno == a.longrepr.reprcrash.lineno
        assert rep.longrepr.reprcrash.message == a.longrepr.reprcrash.message
        assert rep.longrepr.reprcrash.path == a.longrepr.reprcrash.path
        assert rep.longrepr.reprtraceback.entrysep == a.longrepr.reprtraceback.entrysep
        assert (
            rep.longrepr.reprtraceback.extraline == a.longrepr.reprtraceback.extraline
        )
        assert rep.longrepr.reprtraceback.style == a.longrepr.reprtraceback.style
        assert rep.longrepr.sections == a.longrepr.sections
        # Missing section attribute PR171
        assert added_section in a.longrepr.sections

    def test_reprentries_serialization_170(self, testdir):
        from _pytest._code.code import ReprEntry

        reprec = testdir.inline_runsource(
            """
                            def test_repr_entry():
                                x = 0
                                assert x
                        """,
            "--showlocals",
        )
        reports = reprec.getreports("pytest_runtest_logreport")
        assert len(reports) == 3
        rep = reports[1]
        d = serialize_report(rep)
        a = unserialize_report("testreport", d)

        rep_entries = rep.longrepr.reprtraceback.reprentries
        a_entries = a.longrepr.reprtraceback.reprentries
        for i in range(len(a_entries)):
            assert isinstance(rep_entries[i], ReprEntry)
            assert rep_entries[i].lines == a_entries[i].lines
            assert rep_entries[i].localssep == a_entries[i].localssep
            assert rep_entries[i].reprfileloc.lineno == a_entries[i].reprfileloc.lineno
            assert (
                rep_entries[i].reprfileloc.message == a_entries[i].reprfileloc.message
            )
            assert rep_entries[i].reprfileloc.path == a_entries[i].reprfileloc.path
            assert rep_entries[i].reprfuncargs.args == a_entries[i].reprfuncargs.args
            assert rep_entries[i].reprlocals.lines == a_entries[i].reprlocals.lines
            assert rep_entries[i].style == a_entries[i].style

    def test_reprentries_serialization_196(self, testdir):
        from _pytest._code.code import ReprEntryNative

        reprec = testdir.inline_runsource(
            """
                            def test_repr_entry_native():
                                x = 0
                                assert x
                        """,
            "--tb=native",
        )
        reports = reprec.getreports("pytest_runtest_logreport")
        assert len(reports) == 3
        rep = reports[1]
        d = serialize_report(rep)
        a = unserialize_report("testreport", d)

        rep_entries = rep.longrepr.reprtraceback.reprentries
        a_entries = a.longrepr.reprtraceback.reprentries
        for i in range(len(a_entries)):
            assert isinstance(rep_entries[i], ReprEntryNative)
            assert rep_entries[i].lines == a_entries[i].lines

    def test_itemreport_outcomes(self, testdir):
        reprec = testdir.inline_runsource(
            """
            import py
            def test_pass(): pass
            def test_fail(): 0/0
            @py.test.mark.skipif("True")
            def test_skip(): pass
            def test_skip_imperative():
                py.test.skip("hello")
            @py.test.mark.xfail("True")
            def test_xfail(): 0/0
            def test_xfail_imperative():
                py.test.xfail("hello")
        """
        )
        reports = reprec.getreports("pytest_runtest_logreport")
        assert len(reports) == 17  # with setup/teardown "passed" reports
        for rep in reports:
            d = serialize_report(rep)
            check_marshallable(d)
            newrep = unserialize_report("testreport", d)
            assert newrep.passed == rep.passed
            assert newrep.failed == rep.failed
            assert newrep.skipped == rep.skipped
            if newrep.skipped and not hasattr(newrep, "wasxfail"):
                assert len(newrep.longrepr) == 3
            assert newrep.outcome == rep.outcome
            assert newrep.when == rep.when
            assert newrep.keywords == rep.keywords
            if rep.failed:
                assert newrep.longreprtext == rep.longreprtext

    def test_collectreport_passed(self, testdir):
        reprec = testdir.inline_runsource("def test_func(): pass")
        reports = reprec.getreports("pytest_collectreport")
        for rep in reports:
            d = serialize_report(rep)
            check_marshallable(d)
            newrep = unserialize_report("collectreport", d)
            assert newrep.passed == rep.passed
            assert newrep.failed == rep.failed
            assert newrep.skipped == rep.skipped

    def test_collectreport_fail(self, testdir):
        reprec = testdir.inline_runsource("qwe abc")
        reports = reprec.getreports("pytest_collectreport")
        assert reports
        for rep in reports:
            d = serialize_report(rep)
            check_marshallable(d)
            newrep = unserialize_report("collectreport", d)
            assert newrep.passed == rep.passed
            assert newrep.failed == rep.failed
            assert newrep.skipped == rep.skipped
            if rep.failed:
                assert newrep.longrepr == str(rep.longrepr)

    def test_extended_report_deserialization(self, testdir):
        reprec = testdir.inline_runsource("qwe abc")
        reports = reprec.getreports("pytest_collectreport")
        assert reports
        for rep in reports:
            rep.extra = True
            d = serialize_report(rep)
            check_marshallable(d)
            newrep = unserialize_report("collectreport", d)
            assert newrep.extra
            assert newrep.passed == rep.passed
            assert newrep.failed == rep.failed
            assert newrep.skipped == rep.skipped
            if rep.failed:
                assert newrep.longrepr == str(rep.longrepr)


class TestWorkerInteractor:
    def test_basic_collect_and_runtests(self, worker):
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
        rep = unserialize_report(ev.name, ev.kwargs["data"])
        assert rep.nodeid.endswith("::test_func")
        assert rep.passed
        assert rep.when == "call"
        ev = worker.popevent("workerfinished")
        assert "workeroutput" in ev.kwargs

    @pytest.mark.skipif(
        pytest.__version__ >= "3.0", reason="skip at module level illegal in pytest 3.0"
    )
    def test_remote_collect_skip(self, worker):
        worker.testdir.makepyfile(
            """
            import py
            py.test.skip("hello")
        """
        )
        worker.setup()
        ev = worker.popevent("collectionstart")
        assert not ev.kwargs
        ev = worker.popevent()
        assert ev.name == "collectreport"
        ev = worker.popevent()
        assert ev.name == "collectreport"
        rep = unserialize_report(ev.name, ev.kwargs["data"])
        assert rep.skipped
        ev = worker.popevent("collectionfinish")
        assert not ev.kwargs["ids"]

    def test_remote_collect_fail(self, worker):
        worker.testdir.makepyfile("""aasd qwe""")
        worker.setup()
        ev = worker.popevent("collectionstart")
        assert not ev.kwargs
        ev = worker.popevent()
        assert ev.name == "collectreport"
        ev = worker.popevent()
        assert ev.name == "collectreport"
        rep = unserialize_report(ev.name, ev.kwargs["data"])
        assert rep.failed
        ev = worker.popevent("collectionfinish")
        assert not ev.kwargs["ids"]

    def test_runtests_all(self, worker):
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
                rep = unserialize_report(ev.name, ev.kwargs["data"])
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

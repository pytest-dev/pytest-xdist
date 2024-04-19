from __future__ import annotations

import marshal
import pprint
from queue import Queue
import sys
from typing import Any
from typing import Callable
from typing import cast
from typing import Dict
from typing import Union
import uuid

import execnet
import pytest

from xdist.workermanage import NodeManager
from xdist.workermanage import WorkerController


WAIT_TIMEOUT = 10.0


def check_marshallable(d: object) -> None:
    try:
        marshal.dumps(d)  # type: ignore[arg-type]
    except ValueError as e:
        pprint.pprint(d)
        raise ValueError("not marshallable") from e


class EventCall:
    def __init__(self, eventcall: tuple[str, dict[str, Any]]) -> None:
        self.name, self.kwargs = eventcall

    def __str__(self) -> str:
        return f"<EventCall {self.name}(**{self.kwargs})>"


class WorkerSetup:
    def __init__(
        self, request: pytest.FixtureRequest, pytester: pytest.Pytester
    ) -> None:
        self.request = request
        self.pytester = pytester
        self.use_callback = False
        self.events = Queue()  # type: ignore[var-annotated]

    def setup(self) -> None:
        self.pytester.chdir()
        # import os ; os.environ['EXECNET_DEBUG'] = "2"
        self.gateway = execnet.makegateway("execmodel=main_thread_only//popen")
        self.config = config = self.pytester.parseconfigure()
        putevent = self.events.put if self.use_callback else None

        class DummyMananger:
            testrunuid = uuid.uuid4().hex
            specs = [0, 1]

        nodemanager = cast(NodeManager, DummyMananger)

        self.slp = WorkerController(
            nodemanager=nodemanager,
            gateway=self.gateway,
            config=config,
            putevent=putevent,  # type: ignore[arg-type]
        )
        self.request.addfinalizer(self.slp.ensure_teardown)
        self.slp.setup()

    def popevent(self, name: str | None = None) -> EventCall:
        while 1:
            if self.use_callback:
                data = self.events.get(timeout=WAIT_TIMEOUT)
            else:
                data = self.slp.channel.receive(timeout=WAIT_TIMEOUT)
            ev = EventCall(data)
            if name is None or ev.name == name:
                return ev
            print(f"skipping {ev}")

    def sendcommand(self, name: str, **kwargs: Any) -> None:
        self.slp.sendcommand(name, **kwargs)


@pytest.fixture
def worker(request: pytest.FixtureRequest, pytester: pytest.Pytester) -> WorkerSetup:
    return WorkerSetup(request, pytester)


class TestWorkerInteractor:
    UnserializerReport = Callable[
        [Dict[str, Any]], Union[pytest.CollectReport, pytest.TestReport]
    ]

    @pytest.fixture
    def unserialize_report(self, pytestconfig: pytest.Config) -> UnserializerReport:
        def unserialize(
            data: dict[str, Any],
        ) -> pytest.CollectReport | pytest.TestReport:
            return pytestconfig.hook.pytest_report_from_serializable(  # type: ignore[no-any-return]
                config=pytestconfig, data=data
            )

        return unserialize

    def test_basic_collect_and_runtests(
        self, worker: WorkerSetup, unserialize_report: UnserializerReport
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

    def test_remote_collect_skip(
        self, worker: WorkerSetup, unserialize_report: UnserializerReport
    ) -> None:
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
        assert isinstance(rep.longrepr, tuple)
        assert rep.longrepr[2] == "Skipped: hello"
        ev = worker.popevent("collectionfinish")
        assert not ev.kwargs["ids"]

    def test_remote_collect_fail(
        self, worker: WorkerSetup, unserialize_report: UnserializerReport
    ) -> None:
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

    def test_runtests_all(
        self, worker: WorkerSetup, unserialize_report: UnserializerReport
    ) -> None:
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
            for _ in range(3):  # setup/call/teardown
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
        worker.slp.process_from_remote(("<nonono>", {}))
        out, err = capsys.readouterr()
        assert "INTERNALERROR> ValueError: unknown event: <nonono>" in out
        ev = worker.popevent()
        assert ev.name == "errordown"

    def test_steal_work(
        self, worker: WorkerSetup, unserialize_report: UnserializerReport
    ) -> None:
        worker.pytester.makepyfile(
            """
            import time
            def test_func(): time.sleep(1)
            def test_func2(): pass
            def test_func3(): pass
            def test_func4(): pass
        """
        )
        worker.setup()
        ev = worker.popevent("collectionfinish")
        ids = ev.kwargs["ids"]
        assert len(ids) == 4
        worker.sendcommand("runtests_all")

        # wait for test_func setup
        ev = worker.popevent("testreport")
        rep = unserialize_report(ev.kwargs["data"])
        assert rep.nodeid.endswith("::test_func")
        assert rep.when == "setup"

        worker.sendcommand("steal", indices=[1, 2])
        ev = worker.popevent("unscheduled")
        assert ev.kwargs["indices"] == [2]

        reports = [
            ("test_func", "call"),
            ("test_func", "teardown"),
            ("test_func2", "setup"),
            ("test_func2", "call"),
            ("test_func2", "teardown"),
        ]

        for func, when in reports:
            ev = worker.popevent("testreport")
            rep = unserialize_report(ev.kwargs["data"])
            assert rep.nodeid.endswith(f"::{func}")
            assert rep.when == when

        worker.sendcommand("shutdown")

        for when in ["setup", "call", "teardown"]:
            ev = worker.popevent("testreport")
            rep = unserialize_report(ev.kwargs["data"])
            assert rep.nodeid.endswith("::test_func4")
            assert rep.when == when

        ev = worker.popevent("workerfinished")
        assert "workeroutput" in ev.kwargs

    def test_steal_empty_queue(
        self, worker: WorkerSetup, unserialize_report: UnserializerReport
    ) -> None:
        worker.pytester.makepyfile(
            """
            def test_func(): pass
            def test_func2(): pass
        """
        )
        worker.setup()
        ev = worker.popevent("collectionfinish")
        ids = ev.kwargs["ids"]
        assert len(ids) == 2
        worker.sendcommand("runtests_all")

        for when in ["setup", "call", "teardown"]:
            ev = worker.popevent("testreport")
            rep = unserialize_report(ev.kwargs["data"])
            assert rep.nodeid.endswith("::test_func")
            assert rep.when == when

        worker.sendcommand("steal", indices=[0, 1])
        ev = worker.popevent("unscheduled")
        assert ev.kwargs["indices"] == []

        worker.sendcommand("shutdown")

        for when in ["setup", "call", "teardown"]:
            ev = worker.popevent("testreport")
            rep = unserialize_report(ev.kwargs["data"])
            assert rep.nodeid.endswith("::test_func2")
            assert rep.when == when

        ev = worker.popevent("workerfinished")
        assert "workeroutput" in ev.kwargs


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
        f"""
        def test_mainargv(request):
            assert request.config.workerinput["mainargv"] == {outer_argv!r}
        """
    )
    result = pytester.runpytest("-n1")
    assert result.ret == 0


def test_remote_usage_prog(pytester: pytest.Pytester) -> None:
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

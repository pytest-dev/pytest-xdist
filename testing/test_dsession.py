from xdist.dsession import DSession, get_default_max_worker_restart
from xdist.report import report_collection_diff
from xdist.scheduler import EachScheduling, LoadScheduling
from typing import Optional

import pytest
import execnet


class MockGateway:
    def __init__(self) -> None:
        self._count = 0
        self.id = str(self._count)
        self._count += 1


class MockNode:
    def __init__(self) -> None:
        self.sent = []  # type: ignore[var-annotated]
        self.gateway = MockGateway()
        self._shutdown = False

    def send_runtest_some(self, indices) -> None:
        self.sent.extend(indices)

    def send_runtest_all(self) -> None:
        self.sent.append("ALL")

    def shutdown(self) -> None:
        self._shutdown = True

    @property
    def shutting_down(self) -> bool:
        return self._shutdown


class TestEachScheduling:
    def test_schedule_load_simple(self, pytester: pytest.Pytester) -> None:
        node1 = MockNode()
        node2 = MockNode()
        config = pytester.parseconfig("--tx=2*popen")
        sched = EachScheduling(config)
        sched.add_node(node1)
        sched.add_node(node2)
        collection = ["a.py::test_1"]
        assert not sched.collection_is_completed
        sched.add_node_collection(node1, collection)
        assert not sched.collection_is_completed
        sched.add_node_collection(node2, collection)
        assert sched.collection_is_completed
        assert sched.node2collection[node1] == collection
        assert sched.node2collection[node2] == collection
        sched.schedule()
        assert sched.tests_finished
        assert node1.sent == ["ALL"]
        assert node2.sent == ["ALL"]
        sched.mark_test_complete(node1, 0)
        assert sched.tests_finished
        sched.mark_test_complete(node2, 0)
        assert sched.tests_finished

    def test_schedule_remove_node(self, pytester: pytest.Pytester) -> None:
        node1 = MockNode()
        config = pytester.parseconfig("--tx=popen")
        sched = EachScheduling(config)
        sched.add_node(node1)
        collection = ["a.py::test_1"]
        assert not sched.collection_is_completed
        sched.add_node_collection(node1, collection)
        assert sched.collection_is_completed
        assert sched.node2collection[node1] == collection
        sched.schedule()
        assert sched.tests_finished
        crashitem = sched.remove_node(node1)
        assert crashitem
        assert sched.tests_finished
        assert not sched.nodes


class TestLoadScheduling:
    def test_schedule_load_simple(self, pytester: pytest.Pytester) -> None:
        config = pytester.parseconfig("--tx=2*popen")
        sched = LoadScheduling(config)
        sched.add_node(MockNode())
        sched.add_node(MockNode())
        node1, node2 = sched.nodes
        collection = ["a.py::test_1", "a.py::test_2"]
        assert not sched.collection_is_completed
        sched.add_node_collection(node1, collection)
        assert not sched.collection_is_completed
        sched.add_node_collection(node2, collection)
        assert sched.collection_is_completed
        assert sched.node2collection[node1] == collection
        assert sched.node2collection[node2] == collection
        sched.schedule()
        assert not sched.pending
        assert sched.tests_finished
        assert len(node1.sent) == 1
        assert len(node2.sent) == 1
        assert node1.sent == [0]
        assert node2.sent == [1]
        sched.mark_test_complete(node1, node1.sent[0])
        assert sched.tests_finished

    def test_schedule_batch_size(self, pytester: pytest.Pytester) -> None:
        config = pytester.parseconfig("--tx=2*popen")
        sched = LoadScheduling(config)
        sched.add_node(MockNode())
        sched.add_node(MockNode())
        node1, node2 = sched.nodes
        col = ["xyz"] * 6
        sched.add_node_collection(node1, col)
        sched.add_node_collection(node2, col)
        sched.schedule()
        # assert not sched.tests_finished
        sent1 = node1.sent
        sent2 = node2.sent
        assert sent1 == [0, 1]
        assert sent2 == [2, 3]
        assert sched.pending == [4, 5]
        assert sched.node2pending[node1] == sent1
        assert sched.node2pending[node2] == sent2
        assert len(sched.pending) == 2
        sched.mark_test_complete(node1, 0)
        assert node1.sent == [0, 1, 4]
        assert sched.pending == [5]
        assert node2.sent == [2, 3]
        sched.mark_test_complete(node1, 1)
        assert node1.sent == [0, 1, 4, 5]
        assert not sched.pending

    def test_schedule_fewer_tests_than_nodes(self, pytester: pytest.Pytester) -> None:
        config = pytester.parseconfig("--tx=2*popen")
        sched = LoadScheduling(config)
        sched.add_node(MockNode())
        sched.add_node(MockNode())
        sched.add_node(MockNode())
        node1, node2, node3 = sched.nodes
        col = ["xyz"] * 2
        sched.add_node_collection(node1, col)
        sched.add_node_collection(node2, col)
        sched.schedule()
        # assert not sched.tests_finished
        sent1 = node1.sent
        sent2 = node2.sent
        sent3 = node3.sent
        assert sent1 == [0]
        assert sent2 == [1]
        assert sent3 == []
        assert not sched.pending

    def test_schedule_fewer_than_two_tests_per_node(
        self, pytester: pytest.Pytester
    ) -> None:
        config = pytester.parseconfig("--tx=2*popen")
        sched = LoadScheduling(config)
        sched.add_node(MockNode())
        sched.add_node(MockNode())
        sched.add_node(MockNode())
        node1, node2, node3 = sched.nodes
        col = ["xyz"] * 5
        sched.add_node_collection(node1, col)
        sched.add_node_collection(node2, col)
        sched.schedule()
        # assert not sched.tests_finished
        sent1 = node1.sent
        sent2 = node2.sent
        sent3 = node3.sent
        assert sent1 == [0, 3]
        assert sent2 == [1, 4]
        assert sent3 == [2]
        assert not sched.pending

    def test_add_remove_node(self, pytester: pytest.Pytester) -> None:
        node = MockNode()
        config = pytester.parseconfig("--tx=popen")
        sched = LoadScheduling(config)
        sched.add_node(node)
        collection = ["test_file.py::test_func"]
        sched.add_node_collection(node, collection)
        assert sched.collection_is_completed
        sched.schedule()
        assert not sched.pending
        crashitem = sched.remove_node(node)
        assert crashitem == collection[0]

    def test_different_tests_collected(self, pytester: pytest.Pytester) -> None:
        """
        Test that LoadScheduling is reporting collection errors when
        different test ids are collected by workers.
        """

        class CollectHook:
            """
            Dummy hook that stores collection reports.
            """

            def __init__(self):
                self.reports = []

            def pytest_collectreport(self, report):
                self.reports.append(report)

        collect_hook = CollectHook()
        config = pytester.parseconfig("--tx=2*popen")
        config.pluginmanager.register(collect_hook, "collect_hook")
        node1 = MockNode()
        node2 = MockNode()
        sched = LoadScheduling(config)
        sched.add_node(node1)
        sched.add_node(node2)
        sched.add_node_collection(node1, ["a.py::test_1"])
        sched.add_node_collection(node2, ["a.py::test_2"])
        sched.schedule()
        assert len(collect_hook.reports) == 1
        rep = collect_hook.reports[0]
        assert "Different tests were collected between" in rep.longrepr


class TestDistReporter:
    @pytest.mark.xfail
    def test_rsync_printing(self, pytester: pytest.Pytester, linecomp) -> None:
        config = pytester.parseconfig()
        from _pytest.pytest_terminal import TerminalReporter

        rep = TerminalReporter(config, file=linecomp.stringio)
        config.pluginmanager.register(rep, "terminalreporter")
        dsession = DSession(config)

        class gw1:
            id = "X1"
            spec = execnet.XSpec("popen")

        class gw2:
            id = "X2"
            spec = execnet.XSpec("popen")

        # class rinfo:
        #    version_info = (2, 5, 1, 'final', 0)
        #    executable = "hello"
        #    platform = "xyz"
        #    cwd = "qwe"

        # dsession.pytest_xdist_newgateway(gw1, rinfo)
        # linecomp.assert_contains_lines([
        #     "*X1*popen*xyz*2.5*"
        # ])
        dsession.pytest_xdist_rsyncstart(source="hello", gateways=[gw1, gw2])  # type: ignore[attr-defined]
        linecomp.assert_contains_lines(["[X1,X2] rsyncing: hello"])


def test_report_collection_diff_equal() -> None:
    """Test reporting of equal collections."""
    from_collection = to_collection = ["aaa", "bbb", "ccc"]
    assert report_collection_diff(from_collection, to_collection, 1, 2) is None


def test_default_max_worker_restart() -> None:
    class config:
        class option:
            maxworkerrestart: Optional[str] = None
            numprocesses: int = 0

    assert get_default_max_worker_restart(config) is None

    config.option.numprocesses = 2
    assert get_default_max_worker_restart(config) == 8

    config.option.maxworkerrestart = "1"
    assert get_default_max_worker_restart(config) == 1

    config.option.maxworkerrestart = "0"
    assert get_default_max_worker_restart(config) == 0


def test_report_collection_diff_different() -> None:
    """Test reporting of different collections."""
    from_collection = ["aaa", "bbb", "ccc", "YYY"]
    to_collection = ["aZa", "bbb", "XXX", "ccc"]
    error_message = (
        "Different tests were collected between 1 and 2. The difference is:\n"
        "--- 1\n"
        "\n"
        "+++ 2\n"
        "\n"
        "@@ -1,4 +1,4 @@\n"
        "\n"
        "-aaa\n"
        "+aZa\n"
        " bbb\n"
        "+XXX\n"
        " ccc\n"
        "-YYY\n"
        "To see why this happens see Known limitations in documentation"
    )

    msg = report_collection_diff(from_collection, to_collection, "1", "2")
    assert msg == error_message


@pytest.mark.xfail(reason="duplicate test ids not supported yet")
def test_pytest_issue419(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.parametrize('birth_year', [1988, 1988, ])
        def test_2011_table(birth_year):
            pass
    """
    )
    reprec = pytester.inline_run("-n1")
    reprec.assertoutcome(passed=2)
    assert 0

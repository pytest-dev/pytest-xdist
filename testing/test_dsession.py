from xdist.dsession import DSession
from xdist.report import report_collection_diff
from xdist.scheduler import (
    EachScheduling,
    LoadScheduling,
)

import py
import pytest
import execnet

XSpec = execnet.XSpec


def run(item, node, excinfo=None):
    runner = item.config.pluginmanager.getplugin("runner")
    rep = runner.ItemTestReport(item=item, excinfo=excinfo, when="call")
    rep.node = node
    return rep


class MockGateway:
    _count = 0

    def __init__(self):
        self.id = str(self._count)
        self._count += 1


class MockNode:
    def __init__(self):
        self.sent = []
        self.gateway = MockGateway()
        self._shutdown = False

    def send_runtest_some(self, indices):
        self.sent.extend(indices)

    def send_runtest_all(self):
        self.sent.append("ALL")

    def shutdown(self):
        self._shutdown = True

    @property
    def shutting_down(self):
        return self._shutdown


def dumpqueue(queue):
    while queue.qsize():
        print(queue.get())


class TestEachScheduling:
    def test_schedule_load_simple(self, testdir):
        node1 = MockNode()
        node2 = MockNode()
        config = testdir.parseconfig("--tx=2*popen")
        sched = EachScheduling(config)
        sched.add_node(node1)
        sched.add_node(node2)
        collection = ["a.py::test_1", ]
        assert not sched.collection_is_completed
        sched.add_node_collection(node1, collection)
        assert not sched.collection_is_completed
        sched.add_node_collection(node2, collection)
        assert sched.collection_is_completed
        assert sched.node2collection[node1] == collection
        assert sched.node2collection[node2] == collection
        sched.schedule()
        assert sched.tests_finished
        assert node1.sent == ['ALL']
        assert node2.sent == ['ALL']
        sched.mark_test_complete(node1, 0)
        assert sched.tests_finished
        sched.mark_test_complete(node2, 0)
        assert sched.tests_finished

    def test_schedule_remove_node(self, testdir):
        node1 = MockNode()
        config = testdir.parseconfig("--tx=popen")
        sched = EachScheduling(config)
        sched.add_node(node1)
        collection = ["a.py::test_1", ]
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
    def test_schedule_load_simple(self, testdir):
        config = testdir.parseconfig("--tx=2*popen")
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

    def test_schedule_batch_size(self, testdir):
        config = testdir.parseconfig("--tx=2*popen")
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
        assert sent1 == [0, 2]
        assert sent2 == [1, 3]
        assert sched.pending == [4, 5]
        assert sched.node2pending[node1] == sent1
        assert sched.node2pending[node2] == sent2
        assert len(sched.pending) == 2
        sched.mark_test_complete(node1, 0)
        assert node1.sent == [0, 2, 4]
        assert sched.pending == [5]
        assert node2.sent == [1, 3]
        sched.mark_test_complete(node1, 2)
        assert node1.sent == [0, 2, 4, 5]
        assert not sched.pending

    def test_schedule_fewer_tests_than_nodes(self, testdir):
        config = testdir.parseconfig("--tx=2*popen")
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

    def test_schedule_fewer_than_two_tests_per_node(self, testdir):
        config = testdir.parseconfig("--tx=2*popen")
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

    def test_add_remove_node(self, testdir):
        node = MockNode()
        config = testdir.parseconfig("--tx=popen")
        sched = LoadScheduling(config)
        sched.add_node(node)
        collection = ["test_file.py::test_func"]
        sched.add_node_collection(node, collection)
        assert sched.collection_is_completed
        sched.schedule()
        assert not sched.pending
        crashitem = sched.remove_node(node)
        assert crashitem == collection[0]

    def test_different_tests_collected(self, testdir):
        """
        Test that LoadScheduling is reporting collection errors when
        different test ids are collected by workers.
        """

        class CollectHook(object):
            """
            Dummy hook that stores collection reports.
            """

            def __init__(self):
                self.reports = []

            def pytest_collectreport(self, report):
                self.reports.append(report)

        collect_hook = CollectHook()
        config = testdir.parseconfig("--tx=2*popen")
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
        assert 'Different tests were collected between' in rep.longrepr


class TestDistReporter:
    @py.test.mark.xfail
    def test_rsync_printing(self, testdir, linecomp):
        config = testdir.parseconfig()
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
        dsession.pytest_xdist_rsyncstart(source="hello", gateways=[gw1, gw2])
        linecomp.assert_contains_lines(["[X1,X2] rsyncing: hello", ])


def test_report_collection_diff_equal():
    """Test reporting of equal collections."""
    from_collection = to_collection = ['aaa', 'bbb', 'ccc']
    assert report_collection_diff(from_collection, to_collection, 1, 2) is None


def test_report_collection_diff_different():
    """Test reporting of different collections."""
    from_collection = ['aaa', 'bbb', 'ccc', 'YYY']
    to_collection = ['aZa', 'bbb', 'XXX', 'ccc']
    error_message = (
        'Different tests were collected between 1 and 2. The difference is:\n'
        '--- 1\n'
        '\n'
        '+++ 2\n'
        '\n'
        '@@ -1,4 +1,4 @@\n'
        '\n'
        '-aaa\n'
        '+aZa\n'
        ' bbb\n'
        '+XXX\n'
        ' ccc\n'
        '-YYY')

    msg = report_collection_diff(from_collection, to_collection, '1', '2')
    assert msg == error_message


@pytest.mark.xfail(reason="duplicate test ids not supported yet")
def test_pytest_issue419(testdir):
    testdir.makepyfile("""
        import pytest

        @pytest.mark.parametrize('birth_year', [1988, 1988, ])
        def test_2011_table(birth_year):
            pass
    """)
    reprec = testdir.inline_run("-n1")
    reprec.assertoutcome(passed=2)
    assert 0

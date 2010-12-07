from xdist.dsession import DSession, LoadScheduling, EachScheduling
from _pytest import main as outcome
import py
import execnet

XSpec = execnet.XSpec

def run(item, node, excinfo=None):
    runner = item.config.pluginmanager.getplugin("runner")
    rep = runner.ItemTestReport(item=item,
        excinfo=excinfo, when="call")
    rep.node = node
    return rep

class MockNode:
    def __init__(self):
        self.sent = []

    def send_runtest(self, nodeid):
        self.sent.append(nodeid)

    def send_runtest_all(self):
        self.sent.append("ALL")

    def sendlist(self, items):
        self.sent.extend(items)

    def shutdown(self):
        self._shutdown=True

def dumpqueue(queue):
    while queue.qsize():
        print(queue.get())

class TestEachScheduling:
    def test_schedule_load_simple(self):
        node1 = MockNode()
        node2 = MockNode()
        sched = EachScheduling(2)
        sched.addnode(node1)
        sched.addnode(node2)
        collection = ["a.py::test_1", ]
        assert not sched.collection_is_completed
        sched.addnode_collection(node1, collection)
        assert not sched.collection_is_completed
        sched.addnode_collection(node2, collection)
        assert sched.collection_is_completed
        assert sched.node2collection[node1] == collection
        assert sched.node2collection[node2] == collection
        sched.init_distribute()
        assert not sched.tests_finished()
        assert node1.sent == ['ALL']
        assert node2.sent == ['ALL']
        sched.remove_item(node1, collection[0])
        assert not sched.tests_finished()
        sched.remove_item(node2, collection[0])
        assert sched.tests_finished()

    def test_schedule_remove_node(self):
        node1 = MockNode()
        sched = EachScheduling(1)
        sched.addnode(node1)
        collection = ["a.py::test_1", ]
        assert not sched.collection_is_completed
        sched.addnode_collection(node1, collection)
        assert sched.collection_is_completed
        assert sched.node2collection[node1] == collection
        sched.init_distribute()
        assert not sched.tests_finished()
        crashitem = sched.remove_node(node1)
        assert crashitem
        assert sched.tests_finished()
        assert not sched.hasnodes()

class TestLoadScheduling:
    def test_schedule_load_simple(self):
        node1 = MockNode()
        node2 = MockNode()
        sched = LoadScheduling(2)
        sched.addnode(node1)
        sched.addnode(node2)
        collection = ["a.py::test_1", "a.py::test_2"]
        assert not sched.collection_is_completed
        sched.addnode_collection(node1, collection)
        assert not sched.collection_is_completed
        sched.addnode_collection(node2, collection)
        assert sched.collection_is_completed
        assert sched.node2collection[node1] == collection
        assert sched.node2collection[node2] == collection
        sched.init_distribute()
        assert not sched.tests_finished()
        assert len(node1.sent) == 1
        assert len(node2.sent) == 1
        x = sorted(node1.sent + node2.sent)
        assert x == collection
        sched.remove_item(node1, node1.sent[0])
        sched.remove_item(node2, node2.sent[0])
        assert sched.tests_finished()
        assert not sched.pending

    def test_init_distribute_chunksize(self):
        sched = LoadScheduling(2)
        node1 = MockNode()
        node2 = MockNode()
        sched.addnode(node1)
        sched.addnode(node2)
        sched.ITEM_CHUNKSIZE = 2
        col = ["xyz"] * (2*sched.ITEM_CHUNKSIZE +1)
        sched.addnode_collection(node1, col)
        sched.addnode_collection(node2, col)
        sched.init_distribute()
        sent1 = node1.sent
        sent2 = node2.sent
        chunkitems = col[:sched.ITEM_CHUNKSIZE]
        assert sent1 == chunkitems
        assert sent2 == chunkitems
        assert sched.node2pending[node1] == sent1
        assert sched.node2pending[node2] == sent2
        assert len(sched.pending) == 1
        for node in (node1, node2):
            for i in range(sched.ITEM_CHUNKSIZE):
                sched.remove_item(node, "xyz")
        assert not sched.pending

    def test_add_remove_node(self):
        node = MockNode()
        sched = LoadScheduling(1)
        sched.addnode(node)
        collection = ["test_file.py::test_func"]
        sched.addnode_collection(node, collection)
        assert sched.collection_is_completed
        sched.init_distribute()
        assert not sched.pending
        crashitem = sched.remove_node(node)
        assert crashitem == collection[0]


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
        #class rinfo:
        #    version_info = (2, 5, 1, 'final', 0)
        #    executable = "hello"
        #    platform = "xyz"
        #    cwd = "qwe"

        #dsession.pytest_xdist_newgateway(gw1, rinfo)
        #linecomp.assert_contains_lines([
        #    "*X1*popen*xyz*2.5*"
        #])
        dsession.pytest_xdist_rsyncstart(source="hello", gateways=[gw1, gw2])
        linecomp.assert_contains_lines([
            "[X1,X2] rsyncing: hello",
        ])

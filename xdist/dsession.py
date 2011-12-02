import pytest, py
import sys
from xdist.slavemanage import NodeManager
queue = py.builtin._tryimport('queue', 'Queue')

class EachScheduling:

    def __init__(self, numnodes, log=None):
        self.numnodes = numnodes
        self.node2collection = {}
        self.node2pending = {}
        if log is None:
            self.log = py.log.Producer("eachsched")
        else:
            self.log = log.loadsched
        self.collection_is_completed = False

    def hasnodes(self):
        return bool(self.node2pending)

    def addnode(self, node):
        self.node2collection[node] = None

    def tests_finished(self):
        if not self.collection_is_completed:
            return False
        return True

    def addnode_collection(self, node, collection):
        assert not self.collection_is_completed
        assert self.node2collection[node] is None
        self.node2collection[node] = list(collection)
        self.node2pending[node] = []
        if len(self.node2pending) >= self.numnodes:
            self.collection_is_completed = True

    def remove_item(self, node, item):
        self.node2pending[node].remove(item)

    def remove_node(self, node):
        # KeyError if we didn't get an addnode() yet
        pending = self.node2pending.pop(node)
        if not pending:
            return
        crashitem = pending.pop(0)
        # XXX what about the rest of pending?
        return crashitem

    def init_distribute(self):
        assert self.collection_is_completed
        for node, pending in self.node2pending.items():
            node.send_runtest_all()
            pending[:] = self.node2collection[node]

class LoadScheduling:
    LOAD_THRESHOLD_NEWITEMS = 5
    ITEM_CHUNKSIZE = 10

    def __init__(self, numnodes, log=None):
        self.numnodes = numnodes
        self.node2pending = {}
        self.node2collection = {}
        self.pending = []
        if log is None:
            self.log = py.log.Producer("loadsched")
        else:
            self.log = log.loadsched
        self.collection_is_completed = False

    def hasnodes(self):
        return bool(self.node2pending)

    def addnode(self, node):
        self.node2pending[node] = []

    def tests_finished(self):
        if not self.collection_is_completed or self.pending:
            return False
        #for items in self.node2pending.values():
        #    if items:
        #        return False
        return True

    def addnode_collection(self, node, collection):
        assert not self.collection_is_completed
        assert node in self.node2pending
        self.node2collection[node] = list(collection)
        if len(self.node2collection) >= self.numnodes:
            self.collection_is_completed = True

    def remove_item(self, node, item):
        if item not in self.item2nodes:
            raise AssertionError(item, self.item2nodes)
        nodes = self.item2nodes[item]
        if node in nodes: # the node might have gone down already
            nodes.remove(node)
        #if not nodes:
        #    del self.item2nodes[item]
        pending = self.node2pending[node]
        pending.remove(item)
        # pre-load items-to-test if the node may become ready
        if self.pending and len(pending) < self.LOAD_THRESHOLD_NEWITEMS:
            item = self.pending.pop(0)
            pending.append(item)
            self.item2nodes.setdefault(item, []).append(node)
            node.send_runtest(item)
        self.log("items waiting for node: %d" %(len(self.pending)))
        #self.log("item2pending still executing: %s" %(self.item2nodes,))
        #self.log("node2pending: %s" %(self.node2pending,))

    def remove_node(self, node):
        pending = self.node2pending.pop(node)
        # KeyError if we didn't get an addnode() yet
        for item in pending:
            l = self.item2nodes[item]
            l.remove(node)
            if not l:
                del self.item2nodes[item]
        if not pending:
            return
        crashitem = pending.pop(0)
        self.pending.extend(pending)
        return crashitem

    def init_distribute(self):
        assert self.collection_is_completed
        assert not hasattr(self, 'item2nodes')
        self.item2nodes = {}
        # XXX allow nodes to have different collections
        col = list(self.node2collection.values())[0]
        for node, collection in self.node2collection.items():
            assert collection == col
        self.pending = col
        if not col:
            return
        available = list(self.node2pending.items())
        num_available = self.numnodes
        max_one_round = num_available * self.ITEM_CHUNKSIZE -1
        for i, item in enumerate(self.pending):
            nodeindex = i % num_available
            node, pending = available[nodeindex]
            node.send_runtest(item)
            self.item2nodes.setdefault(item, []).append(node)
            pending.append(item)
            if i >= max_one_round:
                break
        del self.pending[:i+1]

class Interrupted(KeyboardInterrupt):
    """ signals an immediate interruption. """

class DSession:
    def __init__(self, config):
        self.config = config
        self.log = py.log.Producer("dsession")
        if not config.option.debug:
            py.log.setconsumer(self.log._keywords, None)
        self.shuttingdown = False
        self.countfailures = 0
        self.maxfail = config.getvalue("maxfail")
        self.queue = queue.Queue()
        try:
            self.terminal = config.pluginmanager.getplugin("terminalreporter")
        except KeyError:
            self.terminal = None
        else:
            self.trdist = TerminalDistReporter(config)
            config.pluginmanager.register(self.trdist, "terminaldistreporter")

    def report_line(self, line):
        if self.terminal and self.config.option.verbose >= 0:
            self.terminal.write_line(line)

    @pytest.mark.trylast
    def pytest_sessionstart(self, session):
        self.nodemanager = NodeManager(self.config)
        self.nodemanager.setup_nodes(putevent=self.queue.put)

    def pytest_sessionfinish(self, session):
        """ teardown any resources after a test run. """
        nm = getattr(self, 'nodemanager', None) # if not fully initialized
        if nm is not None:
            nm.teardown_nodes()

    def pytest_collection(self):
        # prohibit collection of test items in master process
        return True

    def pytest_runtestloop(self):
        numnodes = len(self.nodemanager.specs)
        dist = self.config.getvalue("dist")
        if dist == "load":
            self.sched = LoadScheduling(numnodes, log=self.log)
        elif dist == "each":
            self.sched = EachScheduling(numnodes, log=self.log)
        else:
            assert 0, dist
        self.shouldstop = False
        self.session_finished = False
        while not self.session_finished:
            self.loop_once()
            if self.shouldstop:
                raise Interrupted(str(self.shouldstop))
        return True

    def loop_once(self):
        """ process one callback from one of the slaves. """
        while 1:
            try:
                eventcall = self.queue.get(timeout=2.0)
                break
            except queue.Empty:
                continue
        callname, kwargs = eventcall
        assert callname, kwargs
        method = "slave_" + callname
        call = getattr(self, method)
        self.log("calling method: %s(**%s)" % (method, kwargs))
        call(**kwargs)
        if self.sched.tests_finished():
            self.triggershutdown()

    #
    # callbacks for processing events from slaves
    #

    def slave_slaveready(self, node, slaveinfo):
        node.slaveinfo = slaveinfo
        node.slaveinfo['id'] = node.gateway.id
        node.slaveinfo['spec'] = node.gateway.spec
        self.config.hook.pytest_testnodeready(node=node)
        self.sched.addnode(node)
        if self.shuttingdown:
            node.shutdown()

    def slave_slavefinished(self, node):
        self.config.hook.pytest_testnodedown(node=node, error=None)
        if node.slaveoutput['exitstatus'] == 2: # keyboard-interrupt
            self.shouldstop = "%s received keyboard-interrupt" % (node,)
            self.slave_errordown(node, "keyboard-interrupt")
            return
        crashitem = self.sched.remove_node(node)
        #assert not crashitem, (crashitem, node)
        if self.shuttingdown and not self.sched.hasnodes():
            self.session_finished = True

    def slave_errordown(self, node, error):
        self.config.hook.pytest_testnodedown(node=node, error=error)
        try:
            crashitem = self.sched.remove_node(node)
        except KeyError:
            pass
        else:
            if crashitem:
                self.handle_crashitem(crashitem, node)
                #self.report_line("item crashed on node: %s" % crashitem)
        if not self.sched.hasnodes():
            self.session_finished = True

    def slave_collectionfinish(self, node, ids):
        self.sched.addnode_collection(node, ids)
        if self.terminal:
            self.trdist.setstatus(node.gateway.spec, "[%d]" %(len(ids)))

        if self.sched.collection_is_completed:
            if self.terminal:
                self.trdist.ensure_show_status()
                self.terminal.write_line("")
                self.terminal.write_line("scheduling tests via %s" %(
                    self.sched.__class__.__name__))

            self.sched.init_distribute()

    def slave_logstart(self, node, nodeid, location):
        self.config.hook.pytest_runtest_logstart(
            nodeid=nodeid, location=location)

    def slave_testreport(self, node, rep):
        if not (rep.passed and rep.when != "call"):
            if rep.when in ("setup", "call"):
                self.sched.remove_item(node, rep.nodeid)
        #self.report_line("testreport %s: %s" %(rep.id, rep.status))
        rep.node = node
        self.config.hook.pytest_runtest_logreport(report=rep)
        self._handlefailures(rep)

    def slave_collectreport(self, node, rep):
        #self.report_line("collectreport %s: %s" %(rep.id, rep.status))
        #rep.node = node
        self._handlefailures(rep)

    def _handlefailures(self, rep):
        if rep.failed:
            self.countfailures += 1
            if self.maxfail and self.countfailures >= self.maxfail:
                self.shouldstop = "stopping after %d failures" % (
                    self.countfailures)

    def triggershutdown(self):
        self.log("triggering shutdown")
        self.shuttingdown = True
        for node in self.sched.node2pending:
            node.shutdown()

    def handle_crashitem(self, nodeid, slave):
        # XXX get more reporting info by recording pytest_runtest_logstart?
        runner = self.config.pluginmanager.getplugin("runner")
        fspath = nodeid.split("::")[0]
        msg = "Slave %r crashed while running %r" %(slave.gateway.id, nodeid)
        rep = runner.TestReport(nodeid, (fspath, None, fspath), (),
            "failed", msg, "???")
        rep.node = slave
        self.config.hook.pytest_runtest_logreport(report=rep)

class TerminalDistReporter:
    def __init__(self, config):
        self.config = config
        self.tr = config.pluginmanager.getplugin("terminalreporter")
        self._status = {}
        self._lastlen = 0

    def write_line(self, msg):
        self.tr.write_line(msg)

    def ensure_show_status(self):
        if not self.tr.hasmarkup:
            self.write_line(self.getstatus())

    def setstatus(self, spec, status, show=True):
        self._status[spec.id] = status
        if show and self.tr.hasmarkup:
            self.rewrite(self.getstatus())

    def getstatus(self):
        parts = ["%s %s" %(spec.id, self._status[spec.id])
                   for spec in self._specs]
        return " / ".join(parts)

    def rewrite(self, line, newline=False):
        pline = line + " " * max(self._lastlen-len(line), 0)
        if newline:
            self._lastlen = 0
            pline += "\n"
        else:
            self._lastlen = len(line)
        self.tr.rewrite(pline, bold=True)

    def pytest_xdist_setupnodes(self, specs):
        self._specs = specs
        for spec in specs:
            self.setstatus(spec, "I", show=False)
        self.setstatus(spec, "I", show=True)
        self.ensure_show_status()

    def pytest_xdist_newgateway(self, gateway):
        if self.config.option.verbose > 0:
            rinfo = gateway._rinfo()
            version = "%s.%s.%s" % rinfo.version_info[:3]
            self.rewrite("[%s] %s Python %s cwd: %s" % (
                gateway.id, rinfo.platform, version, rinfo.cwd),
                newline=True)
        self.setstatus(gateway.spec, "C")

    def pytest_testnodeready(self, node):
        if self.config.option.verbose > 0:
            d = node.slaveinfo
            infoline = "[%s] Python %s" %(
                d['id'],
                d['version'].replace('\n', ' -- '),)
            self.rewrite(infoline, newline=True)
        self.setstatus(node.gateway.spec, "ok")

    def pytest_testnodedown(self, node, error):
        if not error:
            return
        self.write_line("[%s] node down: %s" %(node.gateway.id, error))

    #def pytest_xdist_rsyncstart(self, source, gateways):
    #    targets = ",".join([gw.id for gw in gateways])
    #    msg = "[%s] rsyncing: %s" %(targets, source)
    #    self.write_line(msg)
    #def pytest_xdist_rsyncfinish(self, source, gateways):
    #    targets = ", ".join(["[%s]" % gw.id for gw in gateways])
    #    self.write_line("rsyncfinish: %s -> %s" %(source, targets))


import py
import sys
from xdist.nodemanage import NodeManager
from py._test import session
import kwlog
queue = py.builtin._tryimport('queue', 'Queue')

def dsession_main(config):
    config.pluginmanager.do_configure(config)
    session = DSession(config)
    trdist = TerminalDistReporter(config)
    config.pluginmanager.register(trdist, "terminaldistreporter")
    exitcode = session.main()
    config.pluginmanager.do_unconfigure(config)
    return exitcode

class LoadScheduling:
    LOAD_THRESHOLD_NEWITEMS = 5
    ITEM_CHUNKSIZE = 10

    def __init__(self, numnodes, log=None):
        self.numnodes = numnodes
        self.node2pending = {}
        self.node2collection = {}
        self.pending = []
        if log is None:
            self.log = kwlog.Producer("loadsched")
        else:
            self.log = log.loadsched

    def hasnodes(self):
        return bool(self.node2pending)

    def addnode(self, node):
        self.node2pending[node] = []

    def collection_is_completed(self):
        return len(self.node2collection) == self.numnodes

    def tests_finished(self):
        if not self.collection_is_completed() or self.pending:
            return False
        for items in self.node2pending.values():
            if items:
                return False
        return True

    def addnode_collection(self, node, collection):
        assert node in self.node2pending
        self.node2collection[node] = list(collection)

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
        assert self.collection_is_completed()
        assert not hasattr(self, 'item2nodes')
        self.item2nodes = {}
        # XXX allow nodes to have different collections
        col = list(self.node2collection.values())[0]
        for node, collection in self.node2collection.items():
            assert collection == col
        self.pending = col
       
    def triggertesting(self):
        if not self.pending:
            return
        available = []
        for node, pending in self.node2pending.items():
            if len(pending) < self.LOAD_THRESHOLD_NEWITEMS:
                available.append((node, pending))
        num_available = len(available)
        if num_available:
            max_one_round = num_available * self.ITEM_CHUNKSIZE -1
            for i, item in enumerate(self.pending):
                nodeindex = i % num_available
                node, pending = available[nodeindex]
                node.send_runtest(item)
                self.item2nodes.setdefault(item, []).append(node)
                #item.ihook.pytest_itemstart(item=item, node=node)
                pending.append(item)
                if i >= max_one_round:
                    break
            del self.pending[:i+1]
        if self.pending:
            self.log.debug("triggertesting remaining:", len(self.pending))

class Interrupted(KeyboardInterrupt):
    """ signals an immediate interruption. """

class DSession:
    def __init__(self, config):
        self.config = config
        self.log = kwlog.Producer("dsession")
        #kwlog.setconsumer(self.log, kwlog.Path("/tmp/x.log"))
        kwlog.setconsumer(self.log, None)
        self.shuttingdown = False
        self.countfailures = 0
        self.maxfail = config.getvalue("maxfail")
        self.queue = queue.Queue()
        try:
            self.terminal = config.pluginmanager.getplugin("terminalreporter")
        except KeyError:
            self.terminal = None

    def report_line(self, line):
        if self.terminal:
            self.terminal.write_line(line)

    def pytest_gwmanage_rsyncstart(self, source, gateways):
        targets = ",".join([gw.id for gw in gateways])
        msg = "[%s] rsyncing: %s" %(targets, source)
        self.report_line(msg)

    #def pytest_gwmanage_rsyncfinish(self, source, gateways):
    #    targets = ", ".join(["[%s]" % gw.id for gw in gateways])
    #    self.write_line("rsyncfinish: %s -> %s" %(source, targets))

    def main(self):
        self.config.hook.pytest_sessionstart(session=self)
        self.setup()
        exitstatus = self.loop()
        self.teardown()
        self.config.hook.pytest_sessionfinish(session=self,
            exitstatus=exitstatus,)
        return exitstatus

    def slave_slaveready(self, node):
        self.sched.addnode(node)
        if self.shuttingdown:
            node.sendcommand("shutdown")

    def slave_slavefinished(self, node):
        crashitem = self.sched.remove_node(node)
        assert not crashitem, (crashitem, node)
        if self.shuttingdown and not self.sched.hasnodes():
            self.session_finished = True

    def slave_errordown(self, node, error):
        self.report_line("node %r down on error: %s" %(node.gateway.id, error,))
        crashitem = self.sched.remove_node(node)
        if crashitem:
            self.handle_crashitem(crashitem, node)
            #self.report_line("item crashed on node: %s" % crashitem)
        if not self.sched.hasnodes():
            self.session_finished = True

    def slave_collectionfinish(self, node, ids):
        self.sched.addnode_collection(node, ids)
        self.report_line("[%s] collected %d test items" %(
            node.gateway.id, len(ids)))

        if self.sched.collection_is_completed():
            self.sched.init_distribute()
            self.sched.triggertesting()

    def slave_logstart(self, node, nodeid, location):
        self.config.hook.pytest_runtest_logstart(
            nodeid=nodeid, location=location)

    def slave_testreport(self, node, rep):
        self.sched.remove_item(node, rep.nodeid)
        #self.report_line("testreport %s: %s" %(rep.id, rep.status))
        self.config.hook.pytest_runtest_logreport(report=rep)
        self._handlefailures(rep)

    def slave_collectreport(self, node, rep):
        #self.report_line("collectreport %s: %s" %(rep.id, rep.status))
        self._handlefailures(rep)

    def _handlefailures(self, rep):
        if rep.failed:
            self.countfailures += 1
            if self.maxfail and self.countfailures >= self.maxfail:
                self.shouldstop = "stopping after %d failures" % (
                    self.countfailures)

    def loop(self):
        self.sched = LoadScheduling(len(self.config.option.tx), log=self.log)
        self.shouldstop = False
        self.session_finished = False
        exitstatus = 0
        try:
            while not (self.session_finished or self.shouldstop):
                self.loop_once()
            if self.shouldstop:
                raise Interrupted(str(self.shouldstop))
        except KeyboardInterrupt:
            excinfo = py.code.ExceptionInfo()
            self.config.hook.pytest_keyboard_interrupt(excinfo=excinfo)
            exitstatus = session.EXIT_INTERRUPTED
        except:
            self.config.pluginmanager.notify_exception()
            exitstatus = session.EXIT_INTERNALERROR
        #self.config.pluginmanager.unregister(loopstate)
        if exitstatus == 0 and self.countfailures:
            exitstatus = session.EXIT_TESTSFAILED
        return exitstatus

    def loop_once(self):
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
        self.log.debug("calling method: %s(**%s)" % (method, kwargs))
        call(**kwargs)
        if self.sched.tests_finished():
            self.triggershutdown()

    def triggershutdown(self):
        self.shuttingdown = True
        for node in self.sched.node2pending:
            node.shutdown()

    def handle_crashitem(self, nodeid, slave):
        # XXX get more reporting info by recording pytest_runtest_logstart?
        runner = self.config.pluginmanager.getplugin("runner")
        fspath = nodeid.split("::")[0]
        msg = "Slave %r crashed while running %r" %(slave.gateway.id, nodeid)
        rep = runner.TestReport(nodeid, (), fspath, (fspath, None, fspath), (),
            "failed", msg, "???")
        self.config.hook.pytest_runtest_logreport(report=rep)

    def setup(self):
        """ setup any neccessary resources ahead of the test run. """
        if not self.config.getvalue("verbose"):
            self.report_line("instantiating gateways (use -v for details): %s" %
                ",".join(self.config.option.tx))
        self.nodemanager = NodeManager(self.config)
        self.nodemanager.setup_nodes(putevent=self.queue.put)

    def teardown(self):
        """ teardown any resources after a test run. """
        self.nodemanager.teardown_nodes()

class TerminalDistReporter:
    def __init__(self, config):
        self.gateway2info = {}
        self.config = config
        self.tplugin = config.pluginmanager.getplugin("terminal")
        self.tr = config.pluginmanager.getplugin("terminalreporter")

    def write_line(self, msg):
        self.tr.write_line(msg)

    def pytest_itemstart(self, __multicall__):
        try:
            __multicall__.methods.remove(self.tr.pytest_itemstart)
        except KeyError:
            pass

    def pytest_runtest_logreport(self, report):
        if hasattr(report, 'node'):
            report.headerlines.append(self.gateway2info.get(
                report.node.gateway,
                "node %r (platinfo not found? strange)"))

    def pytest_gwmanage_newgateway(self, gateway, platinfo):
        #self.write_line("%s instantiated gateway from spec %r" %(gateway.id, gateway.spec._spec))
        d = {}
        d['version'] = self.tplugin.repr_pythonversion(platinfo.version_info)
        d['id'] = gateway.id
        d['spec'] = gateway.spec._spec
        d['platform'] = platinfo.platform
        if self.config.option.verbose:
            d['extra'] = "- " + platinfo.executable
        else:
            d['extra'] = ""
        d['cwd'] = platinfo.cwd
        infoline = ("[%(id)s] %(spec)s -- platform %(platform)s, "
                        "Python %(version)s "
                        "cwd: %(cwd)s"
                        "%(extra)s" % d)
        if self.config.getvalue("verbose"):
            self.write_line(infoline)
        self.gateway2info[gateway] = infoline

    def pytest_testnodeready(self, node):
        if self.config.getvalue("verbose"):
            self.write_line(
                "[%s] txnode ready to receive tests" %(node.gateway.id,))

    def pytest_testnodedown(self, node, error):
        if not error:
            return
        self.write_line("[%s] node down, error: %s" %(node.gateway.id, error))

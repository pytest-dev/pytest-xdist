import difflib
import itertools
from _pytest.runner import CollectReport

import pytest
import py
from xdist.slavemanage import NodeManager, parse_spec_config


queue = py.builtin._tryimport('queue', 'Queue')


class EachScheduling:
    """Implement scheduling of test items on all nodes

    If a node gets added after the test run is started then it is
    assumed to replace a node which got removed before it finished
    its collection.  In this case it will only be used if a node
    with the same spec got removed earlier.

    Any nodes added after the run is started will only get items
    assigned if a node with a matching spec was removed before it
    finished all its pending items.  The new node will then be
    assigned the remaining items from the removed node.
    """

    def __init__(self, config, log=None):
        self.config = config
        self.numnodes = len(parse_spec_config(config))
        self.node2collection = {}
        self.node2pending = {}
        self._started = []
        self._removed2pending = {}
        if log is None:
            self.log = py.log.Producer("eachsched")
        else:
            self.log = log.eachsched
        self.collection_is_completed = False

    @property
    def nodes(self):
        """A list of all nodes in the scheduler."""
        return list(self.node2pending.keys())

    @property
    def tests_finished(self):
        if not self.collection_is_completed:
            return False
        if self._removed2pending:
            return False
        for pending in self.node2pending.values():
            if len(pending) >= 2:
                return False
        return True

    @property
    def has_pending(self):
        """Return True if there are pending test items

        This indicates that collection has finished and nodes are
        still processing test items, so this can be thought of as
        "the scheduler is active".
        """
        for pending in self.node2pending.values():
            if pending:
                return True
        return False

    def add_node(self, node):
        assert node not in self.node2pending
        self.node2pending[node] = []

    def add_node_collection(self, node, collection):
        """Add the collected test items from a node

        Collection is complete once all nodes have submitted their
        collection.  In this case its pending list is set to an empty
        list.  When the collection is already completed this
        submission is from a node which was restarted to replace a
        dead node.  In this case we already assign the pending items
        here.  In either case ``.schedule()`` will instruct the
        node to start running the required tests.
        """
        assert node in self.node2pending
        if not self.collection_is_completed:
            self.node2collection[node] = list(collection)
            self.node2pending[node] = []
            if len(self.node2collection) >= self.numnodes:
                self.collection_is_completed = True
        elif self._removed2pending:
            for deadnode in self._removed2pending:
                if deadnode.gateway.spec == node.gateway.spec:
                    dead_collection = self.node2collection[deadnode]
                    if collection != dead_collection:
                        msg = report_collection_diff(dead_collection,
                                                     collection,
                                                     deadnode.gateway.id,
                                                     node.gateway.id)
                        self.log(msg)
                        return
                    pending = self._removed2pending.pop(deadnode)
                    self.node2pending[node] = pending
                    break

    def mark_test_complete(self, node, item_index, duration=0):
        self.node2pending[node].remove(item_index)

    def remove_node(self, node):
        # KeyError if we didn't get an add_node() yet
        pending = self.node2pending.pop(node)
        if not pending:
            return
        crashitem = self.node2collection[node][pending.pop(0)]
        if pending:
            self._removed2pending[node] = pending
        return crashitem

    def schedule(self):
        """Schedule the test items on the nodes

        If the node's pending list is empty it is a new node which
        needs to run all the tests.  If the pending list is already
        populated (by ``.add_node_collection()``) then it replaces a
        dead node and we only need to run those tests.
        """
        assert self.collection_is_completed
        for node, pending in self.node2pending.items():
            if node in self._started:
                continue
            if not pending:
                pending[:] = range(len(self.node2collection[node]))
                node.send_runtest_all()
            else:
                node.send_runtest_some(pending)
            self._started.append(node)


class LoadScheduling:
    """Implement load scheduling across nodes.

    This distributes the tests collected across all nodes so each test
    is run just once.  All nodes collect and submit the test suite and
    when all collections are received it is verified they are
    identical collections.  Then the collection gets divided up in
    chunks and chunks get submitted to nodes.  Whenever a node finishes
    an item, it calls ``.mark_test_complete()`` which will trigger the
    scheduler to assign more tests if the number of pending tests for
    the node falls below a low-watermark.

    When created, ``numnodes`` defines how many nodes are expected to
    submit a collection. This is used to know when all nodes have
    finished collection or how large the chunks need to be created.

    Attributes:

    :numnodes: The expected number of nodes taking part.  The actual
       number of nodes will vary during the scheduler's lifetime as
       nodes are added by the DSession as they are brought up and
       removed either because of a dead node or normal shutdown.  This
       number is primarily used to know when the initial collection is
       completed.

    :node2collection: Map of nodes and their test collection.  All
       collections should always be identical.

    :node2pending: Map of nodes and the indices of their pending
       tests.  The indices are an index into ``.pending`` (which is
       identical to their own collection stored in
       ``.node2collection``).

    :collection: The one collection once it is validated to be
       identical between all the nodes.  It is initialised to None
       until ``.schedule()`` is called.

    :pending: List of indices of globally pending tests.  These are
       tests which have not yet been allocated to a chunk for a node
       to process.

    :log: A py.log.Producer instance.

    :config: Config object, used for handling hooks.
    """

    def __init__(self, config, log=None):
        self.numnodes = len(parse_spec_config(config))
        self.node2collection = {}
        self.node2pending = {}
        self.pending = []
        self.collection = None
        if log is None:
            self.log = py.log.Producer("loadsched")
        else:
            self.log = log.loadsched
        self.config = config

    @property
    def nodes(self):
        """A list of all nodes in the scheduler."""
        return list(self.node2pending.keys())

    @property
    def collection_is_completed(self):
        """Boolean indication initial test collection is complete.

        This is a boolean indicating all initial participating nodes
        have finished collection.  The required number of initial
        nodes is defined by ``.numnodes``.
        """
        return len(self.node2collection) >= self.numnodes

    @property
    def tests_finished(self):
        """Return True if all tests have been executed by the nodes."""
        if not self.collection_is_completed:
            return False
        if self.pending:
            return False
        for pending in self.node2pending.values():
            if len(pending) >= 2:
                return False
        return True

    @property
    def has_pending(self):
        """Return True if there are pending test items

        This indicates that collection has finished and nodes are
        still processing test items, so this can be thought of as
        "the scheduler is active".
        """
        if self.pending:
            return True
        for pending in self.node2pending.values():
            if pending:
                return True
        return False

    def add_node(self, node):
        """Add a new node to the scheduler.

        From now on the node will be allocated chunks of tests to
        execute.

        Called by the ``DSession.slave_slaveready`` hook when it
        successfully bootstraps a new node.
        """
        assert node not in self.node2pending
        self.node2pending[node] = []

    def add_node_collection(self, node, collection):
        """Add the collected test items from a node

        The collection is stored in the ``.node2collection`` map.
        Called by the ``DSession.slave_collectionfinish`` hook.
        """
        assert node in self.node2pending
        if self.collection_is_completed:
            # A new node has been added later, perhaps an original one died.
            # .schedule() should have
            # been called by now
            assert self.collection
            if collection != self.collection:
                other_node = next(iter(self.node2collection.keys()))
                msg = report_collection_diff(self.collection,
                                             collection,
                                             other_node.gateway.id,
                                             node.gateway.id)
                self.log(msg)
                return
        self.node2collection[node] = list(collection)

    def mark_test_complete(self, node, item_index, duration=0):
        """Mark test item as completed by node

        The duration it took to execute the item is used as a hint to
        the scheduler.

        This is called by the ``DSession.slave_testreport`` hook.
        """
        self.node2pending[node].remove(item_index)
        self.check_schedule(node, duration=duration)

    def check_schedule(self, node, duration=0):
        """Maybe schedule new items on the node

        If there are any globally pending nodes left then this will
        check if the given node should be given any more tests.  The
        ``duration`` of the last test is optionally used as a
        heuristic to influence how many tests the node is assigned.
        """
        if node.shutting_down:
            return

        if self.pending:
            # how many nodes do we have?
            num_nodes = len(self.node2pending)
            # if our node goes below a heuristic minimum, fill it out to
            # heuristic maximum
            items_per_node_min = max(2, len(self.pending) // num_nodes // 4)
            items_per_node_max = max(2, len(self.pending) // num_nodes // 2)
            node_pending = self.node2pending[node]
            if len(node_pending) < items_per_node_min:
                if duration >= 0.1 and len(node_pending) >= 2:
                    # seems the node is doing long-running tests
                    # and has enough items to continue
                    # so let's rather wait with sending new items
                    return
                num_send = items_per_node_max - len(node_pending)
                self._send_tests(node, num_send)
        self.log("num items waiting for node:", len(self.pending))

    def remove_node(self, node):
        """Remove a node from the scheduler

        This should be called either when the node crashed or at
        shutdown time.  In the former case any pending items assigned
        to the node will be re-scheduled.  Called by the
        ``DSession.slave_slavefinished`` and
        ``DSession.slave_errordown`` hooks.

        Return the item which was being executing while the node
        crashed or None if the node has no more pending items.

        """
        pending = self.node2pending.pop(node)
        if not pending:
            return

        # The node crashed, reassing pending items
        crashitem = self.collection[pending.pop(0)]
        self.pending.extend(pending)
        for node in self.node2pending:
            self.check_schedule(node)
        return crashitem

    def schedule(self):
        """Initiate distribution of the test collection

        Initiate scheduling of the items across the nodes.  If this
        gets called again later it behaves the same as calling
        ``.check_schedule()`` on all nodes so that newly added nodes
        will start to be used.

        This is called by the ``DSession.slave_collectionfinish`` hook
        if ``.collection_is_completed`` is True.
        """
        assert self.collection_is_completed

        # Initial distribution already happened, reschedule on all nodes
        if self.collection is not None:
            for node in self.nodes:
                self.check_schedule(node)
            return

        # XXX allow nodes to have different collections
        if not self._check_nodes_have_same_collection():
            self.log('**Different tests collected, aborting run**')
            return

        # Collections are identical, create the index of pending items.
        self.collection = list(self.node2collection.values())[0]
        self.pending[:] = range(len(self.collection))
        if not self.collection:
            return

        # Send a batch of tests to run. If we don't have at least two
        # tests per node, we have to send them all so that we can send
        # shutdown signals and get all nodes working.
        initial_batch = max(len(self.pending) // 4,
                            2 * len(self.nodes))

        # distribute tests round-robin up to the batch size
        # (or until we run out)
        nodes = itertools.cycle(self.nodes)
        for i in range(initial_batch):
            self._send_tests(next(nodes), 1)

        if not self.pending:
            # initial distribution sent all tests, start node shutdown
            for node in self.nodes:
                node.shutdown()

    def _send_tests(self, node, num):
        tests_per_node = self.pending[:num]
        if tests_per_node:
            del self.pending[:num]
            self.node2pending[node].extend(tests_per_node)
            node.send_runtest_some(tests_per_node)

    def _check_nodes_have_same_collection(self):
        """Return True if all nodes have collected the same items.

        If collections differ, this method returns False while logging
        the collection differences and posting collection errors to
        pytest_collectreport hook.
        """
        node_collection_items = list(self.node2collection.items())
        first_node, col = node_collection_items[0]
        same_collection = True
        for node, collection in node_collection_items[1:]:
            msg = report_collection_diff(
                col,
                collection,
                first_node.gateway.id,
                node.gateway.id,
            )
            if msg:
                same_collection = False
                self.log(msg)
                if self.config is not None:
                    rep = CollectReport(
                        node.gateway.id, 'failed',
                        longrepr=msg, result=[])
                    self.config.hook.pytest_collectreport(report=rep)

        return same_collection


def report_collection_diff(from_collection, to_collection, from_id, to_id):
    """Report the collected test difference between two nodes.

    :returns: detailed message describing the difference between the given
    collections, or None if they are equal.
    """
    if from_collection == to_collection:
        return None

    diff = difflib.unified_diff(
        from_collection,
        to_collection,
        fromfile=from_id,
        tofile=to_id,
    )
    error_message = py.builtin._totext(
        'Different tests were collected between {from_id} and {to_id}. '
        'The difference is:\n'
        '{diff}'
    ).format(from_id=from_id, to_id=to_id, diff='\n'.join(diff))
    msg = "\n".join([x.rstrip() for x in error_message.split("\n")])
    return msg


class Interrupted(KeyboardInterrupt):
    """ signals an immediate interruption. """


class DSession:
    """A py.test plugin which runs a distributed test session

    At the beginning of the test session this creates a NodeManager
    instance which creates and starts all nodes.  Nodes then emit
    events processed in the pytest_runtestloop hook using the slave_*
    methods.

    Once a node is started it will automatically start running the
    py.test mainloop with some custom hooks.  This means a node
    automatically starts collecting tests.  Once tests are collected
    it will wait for instructions.
    """
    def __init__(self, config):
        self.config = config
        self.log = py.log.Producer("dsession")
        if not config.option.debug:
            py.log.setconsumer(self.log._keywords, None)
        self.nodemanager = None
        self.sched = None
        self.shuttingdown = False
        self.countfailures = 0
        self.maxfail = config.getvalue("maxfail")
        self.queue = queue.Queue()
        self._session = None
        self._failed_collection_errors = {}
        self._active_nodes = set()
        self._failed_nodes_count = 0
        self._max_slave_restart = self.config.getoption('max_slave_restart')
        if self._max_slave_restart is not None:
            self._max_slave_restart = int(self._max_slave_restart)
        try:
            self.terminal = config.pluginmanager.getplugin("terminalreporter")
        except KeyError:
            self.terminal = None
        else:
            self.trdist = TerminalDistReporter(config)
            config.pluginmanager.register(self.trdist, "terminaldistreporter")

    @property
    def session_finished(self):
        """Return True if the distributed session has finished

        This means all nodes have executed all test items.  This is
        used by pytest_runtestloop to break out of its loop.
        """
        return bool(self.shuttingdown and not self._active_nodes)

    def report_line(self, line):
        if self.terminal and self.config.option.verbose >= 0:
            self.terminal.write_line(line)

    @pytest.mark.trylast
    def pytest_sessionstart(self, session):
        """Creates and starts the nodes.

        The nodes are setup to put their events onto self.queue.  As
        soon as nodes start they will emit the slave_slaveready event.
        """
        self.nodemanager = NodeManager(self.config)
        nodes = self.nodemanager.setup_nodes(putevent=self.queue.put)
        self._active_nodes.update(nodes)
        self._session = session

    def pytest_sessionfinish(self, session):
        """Shutdown all nodes."""
        nm = getattr(self, 'nodemanager', None)  # if not fully initialized
        if nm is not None:
            nm.teardown_nodes()
        self._session = None

    def pytest_collection(self):
        # prohibit collection of test items in master process
        return True

    @pytest.mark.trylast
    def pytest_xdist_make_scheduler(self, config, log):
        dist = config.getvalue("dist")
        if dist == "load":
            return LoadScheduling(config, log)
        elif dist == "each":
            return EachScheduling(config, log)

    def pytest_runtestloop(self):
        self.sched = self.config.hook.pytest_xdist_make_scheduler(
            config=self.config,
            log=self.log
        )
        assert self.sched is not None

        self.shouldstop = False
        while not self.session_finished:
            self.loop_once()
            if self.shouldstop:
                self.triggershutdown()
                raise Interrupted(str(self.shouldstop))
        return True

    def loop_once(self):
        """Process one callback from one of the slaves."""
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
        self.log("calling method", method, kwargs)
        call(**kwargs)
        if self.sched.tests_finished:
            self.triggershutdown()

    #
    # callbacks for processing events from slaves
    #

    def slave_slaveready(self, node, slaveinfo):
        """Emitted when a node first starts up.

        This adds the node to the scheduler, nodes continue with
        collection without any further input.
        """
        node.slaveinfo = slaveinfo
        node.slaveinfo['id'] = node.gateway.id
        node.slaveinfo['spec'] = node.gateway.spec
        self.config.hook.pytest_testnodeready(node=node)
        if self.shuttingdown:
            node.shutdown()
        else:
            self.sched.add_node(node)

    def slave_slavefinished(self, node):
        """Emitted when node executes its pytest_sessionfinish hook.

        Removes the node from the scheduler.

        The node might not be in the scheduler if it had not emitted
        slaveready before shutdown was triggered.
        """
        self.config.hook.pytest_testnodedown(node=node, error=None)
        if node.slaveoutput['exitstatus'] == 2:  # keyboard-interrupt
            self.shouldstop = "%s received keyboard-interrupt" % (node,)
            self.slave_errordown(node, "keyboard-interrupt")
            return
        if node in self.sched.nodes:
            crashitem = self.sched.remove_node(node)
            assert not crashitem, (crashitem, node)
        self._active_nodes.remove(node)

    def slave_errordown(self, node, error):
        """Emitted by the SlaveController when a node dies."""
        self.config.hook.pytest_testnodedown(node=node, error=error)
        try:
            crashitem = self.sched.remove_node(node)
        except KeyError:
            pass
        else:
            if crashitem:
                self.handle_crashitem(crashitem, node)

        self._failed_nodes_count += 1
        maximum_reached = (self._max_slave_restart is not None and
                           self._failed_nodes_count > self._max_slave_restart)
        if maximum_reached:
            if self._max_slave_restart == 0:
                msg = 'Slave restarting disabled'
            else:
                msg = "Maximum crashed slaves reached: %d" % \
                      self._max_slave_restart
            self.report_line(msg)
        else:
            self.report_line("Replacing crashed slave %s" % node.gateway.id)
            self._clone_node(node)
        self._active_nodes.remove(node)

    def slave_collectionfinish(self, node, ids):
        """Slave has finished test collection.

        This adds the collection for this node to the scheduler.  If
        the scheduler indicates collection is finished (i.e. all
        initial nodes have submitted their collections), then tells the
        scheduler to schedule the collected items.  When initiating
        scheduling the first time it logs which scheduler is in use.
        """
        if self.shuttingdown:
            return
        self.config.hook.pytest_xdist_node_collection_finished(node=node,
                                                               ids=ids)
        # tell session which items were effectively collected otherwise
        # the master node will finish the session with EXIT_NOTESTSCOLLECTED
        self._session.testscollected = len(ids)
        self.sched.add_node_collection(node, ids)
        if self.terminal:
            self.trdist.setstatus(node.gateway.spec, "[%d]" % (len(ids)))
        if self.sched.collection_is_completed:
            if self.terminal and not self.sched.has_pending:
                self.trdist.ensure_show_status()
                self.terminal.write_line("")
                self.terminal.write_line("scheduling tests via %s" % (
                    self.sched.__class__.__name__))
            self.sched.schedule()

    def slave_logstart(self, node, nodeid, location):
        """Emitted when a node calls the pytest_runtest_logstart hook."""
        self.config.hook.pytest_runtest_logstart(
            nodeid=nodeid, location=location)

    def slave_testreport(self, node, rep):
        """Emitted when a node calls the pytest_runtest_logreport hook.

        If the node indicates it is finished with a test item, remove
        the item from the pending list in the scheduler.
        """
        if rep.when == "call" or (rep.when == "setup" and not rep.passed):
            self.sched.mark_test_complete(node, rep.item_index, rep.duration)
        # self.report_line("testreport %s: %s" %(rep.id, rep.status))
        rep.node = node
        self.config.hook.pytest_runtest_logreport(report=rep)
        self._handlefailures(rep)

    def slave_collectreport(self, node, rep):
        """Emitted when a node calls the pytest_collectreport hook."""
        if rep.failed:
            self._failed_slave_collectreport(node, rep)

    def _clone_node(self, node):
        """Return new node based on an existing one.

        This is normally for when a node dies, this will copy the spec
        of the existing node and create a new one with a new id.  The
        new node will have been setup so it will start calling the
        "slave_*" hooks and do work soon.
        """
        spec = node.gateway.spec
        spec.id = None
        self.nodemanager.group.allocate_id(spec)
        node = self.nodemanager.setup_node(spec, self.queue.put)
        self._active_nodes.add(node)
        return node

    def _failed_slave_collectreport(self, node, rep):
        # Check we haven't already seen this report (from
        # another slave).
        if rep.longrepr not in self._failed_collection_errors:
            self._failed_collection_errors[rep.longrepr] = True
            self.config.hook.pytest_collectreport(report=rep)
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
        for node in self.sched.nodes:
            node.shutdown()

    def handle_crashitem(self, nodeid, slave):
        # XXX get more reporting info by recording pytest_runtest_logstart?
        # XXX count no of failures and retry N times
        runner = self.config.pluginmanager.getplugin("runner")
        fspath = nodeid.split("::")[0]
        msg = "Slave %r crashed while running %r" % (slave.gateway.id, nodeid)
        rep = runner.TestReport(nodeid, (fspath, None, fspath),
                                (), "failed", msg, "???")
        rep.node = slave
        self.config.hook.pytest_runtest_logreport(report=rep)


class TerminalDistReporter:
    def __init__(self, config):
        self.config = config
        self.tr = config.pluginmanager.getplugin("terminalreporter")
        self._status = {}
        self._lastlen = 0
        self._isatty = getattr(self.tr, 'isatty', self.tr.hasmarkup)

    def write_line(self, msg):
        self.tr.write_line(msg)

    def ensure_show_status(self):
        if not self._isatty:
            self.write_line(self.getstatus())

    def setstatus(self, spec, status, show=True):
        self._status[spec.id] = status
        if show and self._isatty:
            self.rewrite(self.getstatus())

    def getstatus(self):
        parts = ["%s %s" % (spec.id, self._status[spec.id])
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
            infoline = "[%s] Python %s" % (
                d['id'],
                d['version'].replace('\n', ' -- '),)
            self.rewrite(infoline, newline=True)
        self.setstatus(node.gateway.spec, "ok")

    def pytest_testnodedown(self, node, error):
        if not error:
            return
        self.write_line("[%s] node down: %s" % (node.gateway.id, error))

    # def pytest_xdist_rsyncstart(self, source, gateways):
    #    targets = ",".join([gw.id for gw in gateways])
    #    msg = "[%s] rsyncing: %s" %(targets, source)
    #    self.write_line(msg)
    # def pytest_xdist_rsyncfinish(self, source, gateways):
    #    targets = ", ".join(["[%s]" % gw.id for gw in gateways])
    #    self.write_line("rsyncfinish: %s -> %s" %(source, targets))

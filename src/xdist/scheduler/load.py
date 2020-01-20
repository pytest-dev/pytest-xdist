from collections import OrderedDict

from _pytest.runner import CollectReport
from py.log import Producer
from xdist.report import report_collection_diff
from xdist.workermanage import parse_spec_config


class LoadScheduling(object):
    """Implement load scheduling across nodes.

    This distributes the tests collected across all nodes so each test is run
    just once. All nodes collect and submit the list of tests and when all
    collections are received it is verified they are identical collections.
    Then the collection gets divided up in work units, and those work units get
    submitted to nodes. Whenever a node finishes an item, it calls
    ``.mark_test_complete()`` which will trigger the scheduler to assign more
    work units if the number of pending tests for the node falls below a
    low-watermark.

    When created, ``numnodes`` defines how many nodes are expected to submit a
    collection. This is used to know when all nodes have finished collection.

    Work units can also be considered to be "test groups", as the tests inside
    should not be split up across multiple workers, and should be run within
    the same work cycle for a single worker. By default, this does not attempt
    to group the tests in any way, so each work unit would only contain a
    single test. This is designed to be extensible so that custom grouping
    logic can be applied either by making a child class from this and
    overriding the ``get_default_test_group`` method, or by defining the
    ``pytest_xdist_set_test_group_from_nodeid``.hook. If the hook is used, but it returns
    ``None`` for a given test, then this class's default grouping logic will be
    used for that test.

    Attributes:

    :numnodes: The expected number of nodes taking part.  The actual number of
       nodes will vary during the scheduler's lifetime as nodes are added by
       the DSession as they are brought up and removed either because of a dead
       node or normal shutdown.  This number is primarily used to know when the
       initial collection is completed.

    :collection: The final list of tests collected by all nodes once it is
       validated to be identical between all the nodes.  It is initialised to
       None until ``.schedule()`` is called.

    :workqueue: Ordered dictionary that maps all available groups with their
       associated tests (nodeid). Nodeids are in turn associated with their
       completion status. One entry of the workqueue is called a work unit.
       In turn, a collection of work unit is called a workload. All groups in
       this ordered dictionary contain tests that have yet to be scheduled for
       a worker node.

       ::

            workqueue = {
                '<full>/<path>/<to>/test_module.py': {
                    '<full>/<path>/<to>/test_module.py::test_case1': False,
                    '<full>/<path>/<to>/test_module.py::test_case2': False,
                    (...)
                },
                (...)
            }

    :assigned_work: Ordered dictionary that maps worker nodes with their
       assigned work units.

       ::

            assigned_work = {
                '<worker node A>': {
                    '<full>/<path>/<to>/test_module.py': {
                        '<full>/<path>/<to>/test_module.py::test_case1': False,
                        '<full>/<path>/<to>/test_module.py::test_case2': False,
                        (...)
                    },
                    (...)
                },
                (...)
            }

    :registered_collections: Ordered dictionary that maps worker nodes with
       their collection of tests gathered during test discovery.

       ::

            registered_collections = {
                '<worker node A>': [
                    '<full>/<path>/<to>/test_module.py::test_case1',
                    '<full>/<path>/<to>/test_module.py::test_case2',
                ],
                (...)
            }
    :node2collection: Map of nodes and their test collection.  All collections
       should always be identical. This is an alias for
       `.registered_collections``.

    :node2pending: Map of nodes and the names of their pending test groups. The
       names correspond to the names of the work groups that were originally
       stored in ``.workqueue``.

    :log: A py.log.Producer instance.

    :config: Config object, used for handling hooks.
    """

    _producer = "loadsched"

    def __init__(self, config, log=None):
        self.numnodes = len(parse_spec_config(config))
        self.collection = None

        self.workqueue = OrderedDict()
        self.assigned_work = OrderedDict()
        self.registered_collections = OrderedDict()
        self.node2collection = self.registered_collections

        if log is None:
            self.log = Producer(self._producer)
        else:
            self.log = getattr(log, self._producer)

        self.config = config

    @property
    def nodes(self):
        """A list of all active nodes in the scheduler."""
        return list(self.assigned_work.keys())

    @property
    def node2pending(self):
        """Pending work groups for each node."""
        pending = {}
        for node, work_groups in self.assigned_work.items():
            pending[node] = [group for group in work_groups.keys()]
        return pending

    @property
    def collection_is_completed(self):
        """Booleanq indication initial test collection is complete.

        This is a boolean indicating all initial participating nodes have
        finished collection.  The required number of initial nodes is defined
        by ``.numnodes``.
        """
        return len(self.registered_collections) >= self.numnodes

    @property
    def tests_finished(self):
        """Return True if all tests have been executed by the nodes."""
        if not self.collection_is_completed:
            return False

        if self.workqueue:
            return False

        for assigned_unit in self.assigned_work.values():
            if self._pending_of(assigned_unit) >= 2:
                return False

        return True

    @property
    def has_pending(self):
        """Return True if there are pending test items.

        This indicates that collection has finished and nodes are still
        processing test items, so this can be thought of as
        "the scheduler is active".
        """
        if self.workqueue:
            return True

        for assigned_unit in self.assigned_work.values():
            if self._pending_of(assigned_unit) > 0:
                return True

        return False

    @property
    def pending(self):
        """Names of unscheduled work groups."""
        return list(self.workqueue.keys())

    def add_node(self, node):
        """Add a new node to the scheduler.

        From now on the node will be assigned work units to be executed.

        Called by the ``DSession.worker_workerready`` hook when it successfully
        bootstraps a new node.
        """
        assert node not in self.assigned_work
        self.assigned_work[node] = OrderedDict()

    def remove_node(self, node):
        """Remove a node from the scheduler.

        This should be called either when the node crashed or at shutdown time.
        In the former case any pending items assigned to the node will be
        re-scheduled.

        Called by the hooks:

        - ``DSession.worker_workerfinished``.
        - ``DSession.worker_errordown``.

        Removes any completed test items from the test group being executed,
        along with the first non-executed test item (as this is the test item
        that crashed), and then returns the crashed test item's nodeid, or None
        if there's no more pending test items.
        """
        workload = self.assigned_work.pop(node)
        if not self._pending_of(workload):
            return None

        # The node crashed, identify test that crashed
        for test_group, work_unit in workload.copy().items():
            for nodeid, completed in work_unit.copy().items():
                # Remove test items that already ran from the test group.
                del workload[test_group][nodeid]
                if completed:
                    continue
                # Track the nodeid of the crashed test item.
                crashitem = nodeid
                if len(workload[test_group]) == 0:
                    # Remove the test group from the workload as there's no
                    # incomplete work left for it.
                    del workload[test_group]
                break
            else:
                if len(workload[test_group]) == 0:
                    # Remove the test group from the workload as there's no
                    # incomplete work left for it.
                    del workload[test_group]
                continue
            break
        else:
            raise RuntimeError(
                "Unable to identify crashitem on a workload with pending items"
            )

        # Make uncompleted work unit available again
        self.workqueue.update(workload)

        for node in self.assigned_work:
            self._reschedule(node)

        return crashitem

    def add_node_collection(self, node, collection):
        """Add the collected test items from a node.

        The collection is stored in the ``.registered_collections`` dictionary.

        Called by the hook:

        - ``DSession.worker_collectionfinish``.
        """

        # Check that add_node() was called on the node before
        assert node in self.assigned_work

        # A new node has been added later, perhaps an original one died.
        if self.collection_is_completed:

            # Assert that .schedule() should have been called by now
            assert self.collection

            # Check that the new collection matches the official collection
            if collection != self.collection:

                other_node = next(iter(self.registered_collections.keys()))

                msg = report_collection_diff(
                    self.collection, collection, other_node.gateway.id, node.gateway.id
                )
                self.log(msg)
                return

        self.registered_collections[node] = list(collection)

    def mark_test_complete(self, node, item_index, duration=0):
        """Mark test item as completed by node.

        Called by the hook:

        - ``DSession.worker_testreport``.
        """
        nodeid = self.registered_collections[node][item_index]
        test_group = self.get_test_group(nodeid)

        self.assigned_work[node][test_group][nodeid] = True
        self._reschedule(node)

    def _assign_work_unit(self, node):
        """Assign a work unit to a node."""
        assert self.workqueue

        # Grab a unit of work
        test_group, work_unit = self.workqueue.popitem(last=False)

        # Keep track of the assigned work
        assigned_to_node = self.assigned_work.setdefault(node, default=OrderedDict())
        assigned_to_node[test_group] = work_unit

        # Ask the node to execute the workload
        worker_collection = self.registered_collections[node]
        nodeids_indexes = [
            worker_collection.index(nodeid)
            for nodeid, completed in work_unit.items()
            if not completed
        ]

        node.send_runtest_some(nodeids_indexes)

    def get_default_test_group(self, nodeid):
        """Determine the default test grouping of a nodeid.

        This doesn't group tests together. Every test is placed in its own test
        group.
        """
        return nodeid

    def get_test_group(self, nodeid):
        """Determine the test grouping of a nodeid.

        Every test is assigned a test grouping which is determined using the test's
        nodeid. This test grouping effectively determines which tests should not be
        separated from each other, and ensures they are run on the same worker during
        the same work cycle for that worker.
        """
        test_group = self.config.hook.pytest_xdist_set_test_group_from_nodeid(nodeid=nodeid)
        if test_group:
            return test_group[0]
        return self.get_default_test_group(nodeid)

    def _pending_of(self, workload):
        """Return the number of pending tests in a workload."""
        pending = sum(list(group.values()).count(False) for group in workload.values())
        return pending

    def _reschedule(self, node):
        """Maybe schedule new items on the node.

        If there are any globally pending work units left then this will check
        if the given node should be given any more tests.
        """

        # Do not add more work to a node shutting down
        if node.shutting_down:
            return

        # Check that more work is available
        if not self.workqueue:
            node.shutdown()
            return

        self.log("Number of units waiting for node:", len(self.workqueue))

        # Check that the node is almost depleted of work
        # 2: Heuristic of minimum tests to enqueue more work
        if self._pending_of(self.assigned_work[node]) > 2:
            return

        # Pop one unit of work and assign it
        self._assign_work_unit(node)

    def schedule(self):
        """Initiate distribution of the test collection.

        Initiate scheduling of the items across the nodes.  If this gets called
        again later it behaves the same as calling ``._reschedule()`` on all
        nodes so that newly added nodes will start to be used.

        If ``.collection_is_completed`` is True, this is called by the hook:

        - ``DSession.worker_collectionfinish``.
        """
        assert self.collection_is_completed

        # Initial distribution already happened, reschedule on all nodes
        if self.collection is not None:
            for node in self.nodes:
                self._reschedule(node)
            return

        # Check that all nodes collected the same tests
        if not self._check_nodes_have_same_collection():
            self.log("**Different tests collected, aborting run**")
            return

        # Collections are identical, create the final list of items
        self.collection = list(next(iter(self.registered_collections.values())))
        if not self.collection:
            return

        # Determine chunks of work (test groups)
        for nodeid in self.collection:
            test_group = self.get_test_group(nodeid)
            work_unit = self.workqueue.setdefault(test_group, default=OrderedDict())
            work_unit[nodeid] = False

        # allow customization of test group order
        self.config.hook.pytest_xdist_order_test_groups(workqueue=self.workqueue)

        # Avoid having more workers than work
        extra_nodes = len(self.nodes) - len(self.workqueue)

        if extra_nodes > 0:
            self.log("Shuting down {0} nodes".format(extra_nodes))

            for _ in range(extra_nodes):
                unused_node, assigned = self.assigned_work.popitem(last=True)

                self.log("Shuting down unused node {0}".format(unused_node))
                unused_node.shutdown()

        # Assign initial workload
        for node in self.nodes:
            self._assign_work_unit(node)

        # Ensure nodes start with at least two work units if possible (#277)
        for node in self.nodes:
            self._reschedule(node)

        # Initial distribution sent all tests, start node shutdown
        if not self.workqueue:
            for node in self.nodes:
                node.shutdown()

    def _check_nodes_have_same_collection(self):
        """Return True if all nodes have collected the same items.

        If collections differ, this method returns False while logging
        the collection differences and posting collection errors to
        pytest_collectreport hook.
        """
        node_collection_items = list(self.registered_collections.items())
        first_node, col = node_collection_items[0]
        same_collection = True

        for node, collection in node_collection_items[1:]:
            msg = report_collection_diff(
                col, collection, first_node.gateway.id, node.gateway.id
            )
            if not msg:
                continue

            same_collection = False
            self.log(msg)

            if self.config is None:
                continue

            rep = CollectReport(node.gateway.id, "failed", longrepr=msg, result=[])
            self.config.hook.pytest_collectreport(report=rep)

        return same_collection

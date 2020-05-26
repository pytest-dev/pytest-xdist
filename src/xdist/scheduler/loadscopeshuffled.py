from . import LoadScopeScheduling

from collections import OrderedDict
import random
from py.log import Producer


class LoadScopeShuffledScheduling(LoadScopeScheduling):
    """Implement load scheduling across nodes, grouping test by scope

    This distributes the tests collected across all nodes so each test is run
    just once.  All nodes collect and submit the list of tests and when all
    collections are received it is verified they are identical collections.
    Then the collection gets divided up in work units, grouped by test scope,
    and those work units get submitted to nodes. The work units are sampled via
    random.choice and the tests within the workunit are shuffled prior to being
    submitted to nodes.  Whenever a node finishes an item, it calls
    ``.mark_test_complete()`` which will trigger the scheduler
    to assign more work units if the number of pending tests for the node falls
    below a low-watermark.

    When created, ``numnodes`` defines how many nodes are expected to submit a
    collection. This is used to know when all nodes have finished collection.

    This class behaves very much like LoadScopeScheduling, but with modified work assignment
    """
    def __init__(self, config, log=None):
        super(LoadScopeShuffledScheduling, self).__init__(config, log)
        if log is None:
            self.log = Producer("loadscopeshuffledsched")
        else:
            self.log = log.loadscopeshuffledsched

    def _assign_work_unit(self, node):
        """Assign a randomly selected and shuffled work unit to a node."""
        assert self.workqueue

        # Grab a random unit of work
        try:
            scope = random.choice(list(self.workqueue))
        except IndexError:
            # match LoadScopeScheduler error mode - OrderedDict().popitem()
            raise KeyError('dictionary is empty')
        work_unit = self.workqueue.pop(scope)

        # Keep track of the assigned work
        assigned_to_node = self.assigned_work.setdefault(node, default=OrderedDict())
        assigned_to_node[scope] = work_unit

        # Ask the node to execute the workload
        worker_collection = self.registered_collections[node]
        nodeids_indexes = [
            worker_collection.index(nodeid)
            for nodeid, completed in work_unit.items()
            if not completed
        ]
        random.shuffle(nodeids_indexes)  # re-order indexes within a workload
        node.send_runtest_some(nodeids_indexes)

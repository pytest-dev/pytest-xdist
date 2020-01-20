from .load import LoadScheduling
from py.log import Producer


class LoadFileScheduling(LoadScheduling):
    """Implement load scheduling across nodes, but grouping test by file.

    This distributes the tests collected across all nodes so each test is run
    just once.  All nodes collect and submit the list of tests and when all
    collections are received it is verified they are identical collections.
    Then the collection gets divided up in work units, grouped by test file,
    and those work units get submitted to nodes.  Whenever a node finishes an
    item, it calls ``.mark_test_complete()`` which will trigger the scheduler
    to assign more work units if the number of pending tests for the node falls
    below a low-watermark.

    When created, ``numnodes`` defines how many nodes are expected to submit a
    collection. This is used to know when all nodes have finished collection.

    This groups tests by default based on their file.
    """

    _producer = "loadfilesched"

    def get_default_test_group(self, nodeid):
        """Determine the default test grouping of a nodeid, but based on file.

        Tests belonging to the same file will be put into the same test group.
        """
        return nodeid.split("::", 1)[0]

from __future__ import annotations

from collections.abc import Sequence
from itertools import cycle

import pytest

from xdist.remote import Producer
from xdist.workermanage import parse_tx_spec_config
from xdist.workermanage import WorkerController


class SingleCollectScheduling:
    """Implement scheduling with a single test collection phase.

    This differs from LoadScheduling by:
    1. Only collecting tests on the first node
    2. Skipping collection on other nodes
    3. Not checking for collection equality

    This can significantly improve startup time by avoiding redundant collection
    and collection verification across multiple worker processes.
    """

    def __init__(self, config: pytest.Config, log: Producer | None = None) -> None:
        self.numnodes = len(parse_tx_spec_config(config))
        self.node2pending: dict[WorkerController, list[int]] = {}
        self.pending: list[int] = []
        self.collection: list[str] | None = None
        self.first_node: WorkerController | None = None
        if log is None:
            self.log = Producer("singlecollect")
        else:
            self.log = log.singlecollect
        self.config = config
        self.maxschedchunk = self.config.getoption("maxschedchunk")
        self.collection_done = False

    @property
    def nodes(self) -> list[WorkerController]:
        """A list of all nodes in the scheduler."""
        return list(self.node2pending.keys())

    @property
    def collection_is_completed(self) -> bool:
        """Return True once we have collected tests from the first node."""
        return self.collection_done

    @property
    def tests_finished(self) -> bool:
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
    def has_pending(self) -> bool:
        """Return True if there are pending test items."""
        if self.pending:
            return True
        for pending in self.node2pending.values():
            if pending:
                return True
        return False

    def add_node(self, node: WorkerController) -> None:
        """Add a new node to the scheduler."""
        assert node not in self.node2pending
        self.node2pending[node] = []

        # Remember the first node as our collector
        if self.first_node is None:
            self.first_node = node
            self.log(f"Using {node.gateway.id} as collection node")

    def add_node_collection(
        self, node: WorkerController, collection: Sequence[str]
    ) -> None:
        """Only use collection from the first node."""
        # We only care about collection from the first node
        if node == self.first_node:
            self.log(f"Received collection from first node {node.gateway.id}")
            self.collection = list(collection)
            self.collection_done = True
        else:
            # Skip collection verification for other nodes
            self.log(f"Ignoring collection from node {node.gateway.id}")

    def mark_test_complete(
        self, node: WorkerController, item_index: int | str, duration: float = 0
    ) -> None:
        """Mark test item as completed by node."""
        self.node2pending[node].remove(int(item_index) if isinstance(item_index, str) else item_index)
        self.check_schedule(node, duration=duration)

    def mark_test_pending(self, item: str) -> None:
        assert self.collection is not None
        self.pending.insert(
            0,
            self.collection.index(item),
        )
        for node in self.node2pending:
            self.check_schedule(node)

    def remove_pending_tests_from_node(
        self,
        node: WorkerController,
        indices: Sequence[int],
    ) -> None:
        raise NotImplementedError()

    def check_schedule(self, node: WorkerController, duration: float = 0) -> None:
        """Maybe schedule new items on the node."""
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
                # keep at least 2 tests pending even if --maxschedchunk=1
                maxschedchunk = max(2 - len(node_pending), self.maxschedchunk)
                self._send_tests(node, min(num_send, maxschedchunk))
        else:
            node.shutdown()

        self.log("num items waiting for node:", len(self.pending))

    def remove_node(self, node: WorkerController) -> str | None:
        """Remove a node from the scheduler."""
        pending = self.node2pending.pop(node)

        # If this is the first node (collector), reset it
        if node == self.first_node:
            self.first_node = None

        if not pending:
            return None

        # Reassign pending items if the node had any
        assert self.collection is not None
        crashitem = self.collection[pending.pop(0)]
        self.pending.extend(pending)
        for node in self.node2pending:
            self.check_schedule(node)
        return crashitem

    def schedule(self) -> None:
        """Initiate distribution of the test collection."""
        assert self.collection_is_completed

        # Initial distribution already happened, reschedule on all nodes
        if self.pending:
            for node in self.nodes:
                self.check_schedule(node)
            return

        # Initialize the index of pending items
        assert self.collection is not None
        self.pending[:] = range(len(self.collection))
        if not self.collection:
            return

        if self.maxschedchunk is None:
            self.maxschedchunk = len(self.collection)

        # Send a batch of tests to run. If we don't have at least two
        # tests per node, we have to send them all so that we can send
        # shutdown signals and get all nodes working.
        if len(self.pending) < 2 * len(self.nodes):
            # Distribute tests round-robin
            nodes = cycle(self.nodes)
            for _ in range(len(self.pending)):
                self._send_tests(next(nodes), 1)
        else:
            # how many items per node do we have about?
            items_per_node = len(self.collection) // len(self.node2pending)
            # take a fraction of tests for initial distribution
            node_chunksize = min(items_per_node // 4, self.maxschedchunk)
            node_chunksize = max(node_chunksize, 2)
            # and initialize each node with a chunk of tests
            for node in self.nodes:
                self._send_tests(node, node_chunksize)

        if not self.pending:
            # initial distribution sent all tests, start node shutdown
            for node in self.nodes:
                node.shutdown()

    def _send_tests(self, node: WorkerController, num: int) -> None:
        tests_per_node = self.pending[:num]
        if tests_per_node:
            del self.pending[:num]
            self.node2pending[node].extend(tests_per_node)
            node.send_runtest_some(tests_per_node)
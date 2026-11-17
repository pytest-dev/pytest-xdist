"""Tests for LoadScopeScheduling."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import execnet
import pytest

from xdist.scheduler import LoadScopeScheduling
from xdist.workermanage import WorkerController


if TYPE_CHECKING:
    BaseOfMockGateway = execnet.Gateway
    BaseOfMockNode = WorkerController
else:
    BaseOfMockGateway = object
    BaseOfMockNode = object


class MockGateway(BaseOfMockGateway):
    _count = 0

    def __init__(self) -> None:
        self.id = str(MockGateway._count)
        MockGateway._count += 1


class MockNode(BaseOfMockNode):
    def __init__(self) -> None:
        self.sent: list[int] = []
        self.gateway = MockGateway()
        self._shutdown = False

    def send_runtest_some(self, indices: Sequence[int]) -> None:
        self.sent.extend(indices)

    def shutdown(self) -> None:
        self._shutdown = True

    @property
    def shutting_down(self) -> bool:
        return self._shutdown


@pytest.fixture(autouse=True)
def reset_mock_gateway_counter() -> None:
    MockGateway._count = 0


class TestLoadScopeScheduling:
    def test_replacement_worker_with_mismatched_collection_is_skipped(
        self, pytester: pytest.Pytester
    ) -> None:
        """Regression test for https://github.com/pytest-dev/pytest-xdist/issues/1189"""
        config = pytester.parseconfig("--tx=2*popen")
        sched = LoadScopeScheduling(config)

        node1, node2 = MockNode(), MockNode()
        sched.add_node(node1)
        sched.add_node(node2)

        collection = [
            "test_mod.py::test_a",
            "test_mod.py::test_b",
            "test_other.py::test_c",
            "test_other.py::test_d",
        ]
        sched.add_node_collection(node1, collection)
        sched.add_node_collection(node2, collection)
        sched.schedule()

        # Simulate node1 crashing
        sched.remove_node(node1)

        # Replacement worker collects different tests (e.g., due to test file changes)
        replacement_node = MockNode()
        sched.add_node(replacement_node)
        different_collection = [
            "test_mod.py::test_a",
            "test_mod.py::test_b",
            "test_mod.py::test_NEW",  # Different
            "test_other.py::test_d",
        ]
        sched.add_node_collection(replacement_node, different_collection)

        # Replacement node should not be in registered_collections due to mismatch
        assert replacement_node not in sched.registered_collections
        assert replacement_node in sched.assigned_work

        # schedule() should skip unregistered nodes rather than crashing
        sched.schedule()

        assert replacement_node.sent == []
        assert node2 in sched.registered_collections

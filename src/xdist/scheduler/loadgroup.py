from __future__ import annotations

from collections.abc import Sequence

import pytest

from xdist.remote import Producer
from xdist.workermanage import WorkerController

from .loadscope import LoadScopeScheduling


class LoadGroupScheduling(LoadScopeScheduling):
    """Implement load scheduling across nodes, but grouping test by xdist_group mark.

    This class behaves very much like LoadScopeScheduling, but it groups tests by xdist_group mark
    instead of the module or class to which they belong to.
    """

    def __init__(self, config: pytest.Config, log: Producer | None = None) -> None:
        super().__init__(config, log)
        if log is None:
            self.log = Producer("loadgroupsched")
        else:
            self.log = log.loadgroupsched

    def add_node_collection(
        self,
        node: WorkerController,
        collection: Sequence[str],
        group_names: Sequence[str | None] | None = None,
    ) -> None:
        if group_names is not None:
            assert len(collection) == len(group_names)
            collection = [
                f"{nodeid}@{group_name}" if group_name is not None else nodeid
                for nodeid, group_name in zip(collection, group_names)
            ]
        super().add_node_collection(node, collection)

    def _split_scope(self, nodeid: str) -> str:
        """Determine the scope (grouping) of a nodeid.

        There are usually 3 cases for a nodeid::

            example/loadsuite/test/test_beta.py::test_beta0
            example/loadsuite/test/test_delta.py::Delta1::test_delta0
            example/loadsuite/epsilon/__init__.py::epsilon.epsilon

        #. Function in a test module.
        #. Method of a class in a test module.
        #. Doctest in a function in a package.

        With loadgroup, two cases are added::

            example/loadsuite/test/test_beta.py::test_beta0
            example/loadsuite/test/test_delta.py::Delta1::test_delta0
            example/loadsuite/epsilon/__init__.py::epsilon.epsilon
            example/loadsuite/test/test_gamma.py::test_beta0@gname
            example/loadsuite/test/test_delta.py::Gamma1::test_gamma0@gname

        This function will group tests with the scope determined by splitting the first ``@``
        from the right. That is, test will be grouped in a single work unit when they have
        same group name. In the above example, scopes will be::

            example/loadsuite/test/test_beta.py::test_beta0
            example/loadsuite/test/test_delta.py::Delta1::test_delta0
            example/loadsuite/epsilon/__init__.py::epsilon.epsilon
            gname
            gname
        """
        if nodeid.rfind("@") > nodeid.rfind("]"):
            # check the index of ']' to avoid the case: parametrize mark value has '@'
            return nodeid.split("@")[-1]
        else:
            return nodeid

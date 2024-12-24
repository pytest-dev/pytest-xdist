from __future__ import annotations

import pytest

from xdist.remote import Producer

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

    def _split_scope(self, nodeid: str) -> str:
        """Determine the scope (grouping) of a nodeid.

        Either we get a scope from a `xdist_group` mark (and then return that), or we don't do any grouping.
        """
        if nodeid in self.group_markers:
            return self.group_markers[nodeid]
        else:
            return nodeid

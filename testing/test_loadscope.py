from __future__ import annotations

import pytest

from xdist.scheduler.loadscope import LoadScopeScheduling


@pytest.mark.parametrize(
    ("nodeid", "expected"),
    [
        ("test_module.py::test_func[::1-expected]", "test_module.py"),
        (
            "test_module.py::TestClass::test_func[cafe:cafe::cafe-AAAA]",
            "test_module.py::TestClass",
        ),
    ],
)
def test_split_scope_ignores_double_colons_in_parametrize_ids(
    nodeid: str, expected: str
) -> None:
    scheduler = LoadScopeScheduling.__new__(LoadScopeScheduling)
    assert scheduler._split_scope(nodeid) == expected

Join multiple xdist_group.

If a test has more than one xdist_group marker, they will be joined together into a new group. This includes markers from pytestmark and from fixtures. The order does NOT matter.

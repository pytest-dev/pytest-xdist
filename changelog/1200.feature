Now multiple ``xdist_group`` markers are considered when assigning tests to groups (order does not matter).

Previously, only the last marker would assign a test to a group, but now if a test has multiple ``xdist_group`` marks applied (for example via parametrization or via fixtures), they are merged to make a new group.

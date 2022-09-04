Partially restore old initial batch distribution algorithm in ``LoadScheduling``.

pytest orders tests for optimal sequential execution - i. e. avoiding
unnecessary setup and teardown of fixtures. So executing tests in consecutive
chunks is important for optimal performance.

In v1.14, initial test distribution in ``LoadScheduling`` was changed to
round-robin, optimized for the corner case, when the number of tests is less
than ``2 * number of nodes``. At the same time, it became worse for all other
cases.

For example: if some tests use some "heavy" fixture, and these tests fit into
the initial batch, with round-robin distribution the fixture will be created
``min(n_tests, n_workers)`` times, no matter how many other tests there are.

With the old algorithm (before v1.14), if there are enough tests not using
the fixture, the fixture was created only once.

So restore the old behavior for typical cases where the number of tests is
much greater than the number of workers (or, strictly speaking, when there
are at least 2 tests for every node).

In my test suite, where fixtures create Docker containers, this change reduces
total run time by 10-15%.

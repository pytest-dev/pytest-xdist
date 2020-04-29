Add `testrun_uid` fixture. This is a shared value that uniquely identifies a test run among all workers.
This also adds a `PYTEST_XDIST_TESTRUNUID` environment variable that is accessible within a test as well as a command line option `--testrunuid` to manually set the value from outside.

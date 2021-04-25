import pytest


class TestHooks:
    @pytest.fixture(autouse=True)
    def create_test_file(self, testdir):
        testdir.makepyfile(
            """
            import os
            def test_a(): pass
            def test_b(): pass
            def test_c(): pass
        """
        )

    def test_runtest_logreport(self, testdir):
        """Test that log reports from pytest_runtest_logreport when running
        with xdist contain "node", "nodeid", "worker_id", and "testrun_uid" attributes. (#8)
        """
        testdir.makeconftest(
            """
            def pytest_runtest_logreport(report):
                if hasattr(report, 'node'):
                    if report.when == "call":
                        workerid = report.node.workerinput['workerid']
                        testrunuid = report.node.workerinput['testrunuid']
                        if workerid != report.worker_id:
                            print("HOOK: Worker id mismatch: %s %s"
                                   % (workerid, report.worker_id))
                        elif testrunuid != report.testrun_uid:
                            print("HOOK: Testrun uid mismatch: %s %s"
                                   % (testrunuid, report.testrun_uid))
                        else:
                            print("HOOK: %s %s %s"
                                   % (report.nodeid, report.worker_id, report.testrun_uid))
        """
        )
        res = testdir.runpytest("-n1", "-s")
        res.stdout.fnmatch_lines(
            [
                "*HOOK: test_runtest_logreport.py::test_a gw0 *",
                "*HOOK: test_runtest_logreport.py::test_b gw0 *",
                "*HOOK: test_runtest_logreport.py::test_c gw0 *",
                "*3 passed*",
            ]
        )

    def test_node_collection_finished(self, testdir):
        """Test pytest_xdist_node_collection_finished hook (#8)."""
        testdir.makeconftest(
            """
            def pytest_xdist_node_collection_finished(node, ids):
                workerid = node.workerinput['workerid']
                stripped_ids = [x.split('::')[1] for x in ids]
                print("HOOK: %s %s" % (workerid, ', '.join(stripped_ids)))
        """
        )
        res = testdir.runpytest("-n2", "-s")
        res.stdout.fnmatch_lines_random(
            ["*HOOK: gw0 test_a, test_b, test_c", "*HOOK: gw1 test_a, test_b, test_c"]
        )
        res.stdout.fnmatch_lines(["*3 passed*"])


class TestCrashItem:
    @pytest.fixture(autouse=True)
    def create_test_file(self, testdir):
        testdir.makepyfile(
            """
            import os
            def test_a(): pass
            def test_b(): os._exit(1)
            def test_c(): pass
            def test_d(): pass
        """
        )

    def test_handlecrashitem(self, testdir):
        """Test pytest_handlecrashitem hook."""
        testdir.makeconftest(
            """
            test_runs = 0

            def pytest_handlecrashitem(crashitem, report, sched):
                global test_runs

                if test_runs == 0:
                    sched.mark_test_pending(crashitem)
                    test_runs = 1
                else:
                    print("HOOK: pytest_handlecrashitem")
        """
        )
        res = testdir.runpytest("-n2", "-s")
        res.stdout.fnmatch_lines_random(["*HOOK: pytest_handlecrashitem"])
        res.stdout.fnmatch_lines(["*3 passed*"])

import pytest


class TestHooks:

    @pytest.fixture(autouse=True)
    def create_test_file(self, testdir):
        testdir.makepyfile("""
            import os
            def test_a(): pass
            def test_b(): pass
            def test_c(): pass
        """)

    def test_runtest_logreport(self, testdir):
        """Test that log reports from pytest_runtest_logreport when running
        with xdist contain "node", "nodeid" and "worker_id" attributes. (#8)
        """
        testdir.makeconftest("""
            def pytest_runtest_logreport(report):
                if hasattr(report, 'node'):
                    if report.when == "call":
                        slaveid = report.node.slaveinput['slaveid']
                        if slaveid != report.worker_id:
                            print("HOOK: Worker id mismatch: %s %s"
                                   % (slaveid, report.worker_id))
                        else:
                            print("HOOK: %s %s"
                                   % (report.nodeid, report.worker_id))
        """)
        res = testdir.runpytest('-n1', '-s')
        res.stdout.fnmatch_lines([
            '*HOOK: test_runtest_logreport.py::test_a gw0*',
            '*HOOK: test_runtest_logreport.py::test_b gw0*',
            '*HOOK: test_runtest_logreport.py::test_c gw0*',
            '*3 passed*',
        ])

    def test_node_collection_finished(self, testdir):
        """Test pytest_xdist_node_collection_finished hook (#8).
        """
        testdir.makeconftest("""
            def pytest_xdist_node_collection_finished(node, ids):
                slaveid = node.slaveinput['slaveid']
                stripped_ids = [x.split('::')[1] for x in ids]
                print("HOOK: %s %s" % (slaveid, ', '.join(stripped_ids)))
        """)
        res = testdir.runpytest('-n2', '-s')
        res.stdout.fnmatch_lines_random([
            '*HOOK: gw0 test_a, test_b, test_c',
            '*HOOK: gw1 test_a, test_b, test_c',
        ])
        res.stdout.fnmatch_lines([
            '*3 passed*',
        ])

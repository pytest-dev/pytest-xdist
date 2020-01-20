import re
import pytest

from xdist.scheduler import LoadScheduling


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
        with xdist contain "node", "nodeid" and "worker_id" attributes. (#8)
        """
        testdir.makeconftest(
            """
            def pytest_runtest_logreport(report):
                if hasattr(report, 'node'):
                    if report.when == "call":
                        workerid = report.node.workerinput['workerid']
                        if workerid != report.worker_id:
                            print("HOOK: Worker id mismatch: %s %s"
                                   % (workerid, report.worker_id))
                        else:
                            print("HOOK: %s %s"
                                   % (report.nodeid, report.worker_id))
        """
        )
        res = testdir.runpytest("-n1", "-s")
        res.stdout.fnmatch_lines(
            [
                "*HOOK: test_runtest_logreport.py::test_a gw0*",
                "*HOOK: test_runtest_logreport.py::test_b gw0*",
                "*HOOK: test_runtest_logreport.py::test_c gw0*",
                "*3 passed*",
            ]
        )

    def test_node_collection_finished(self, testdir):
        """Test pytest_xdist_node_collection_finished hook (#8).
        """
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


class MockGateway:
    _count = 0

    def __init__(self):
        self.id = str(self._count)
        self._count += 1


class MockNode:
    def __init__(self):
        self.sent = []
        self.gateway = MockGateway()
        self._shutdown = False

    def send_runtest_some(self, indices):
        self.sent.extend(indices)

    def send_runtest_all(self):
        self.sent.append("ALL")

    def shutdown(self):
        self._shutdown = True

    @property
    def shutting_down(self):
        return self._shutdown


class TestSetTestGroupWithLoadScheduler:

    def test_gw0_contains_group_a_and_gw1_contains_group_b(self, testdir):
        testdir.makeconftest(
            """
            import pytest

            def pytest_xdist_set_test_group_from_nodeid(nodeid):
                group_names = ['groupA', 'groupB']
                nodeid_params = nodeid.split('[', 1)[-1].rstrip(']').split('-')
                for name in group_names:
                    if name in nodeid_params:
                        return name
        """
        )
        testdir.makepyfile(
            """
            import pytest
            @pytest.fixture(params=["groupA", "groupB"])
            def group(request):
                return request.param
            @pytest.fixture(params=[1, 2, 3, 4, 5])
            def number(request):
                return request.param
            def test_with_group(number, group): pass
        """
        )
        results = testdir.runpytest("-n3", "-v")
        combos = parse_tests_and_workers_from_output(results.outlines)
        groupings = {}
        for worker_id, status, nodeid in combos:
            groupings.setdefault(worker_id, []).append((nodeid, status))
        gw0_tests = "".join(group[0] for group in groupings["gw0"])
        gw1_tests = "".join(group[0] for group in groupings["gw1"])
        # there is only groupA tests in gw0's assigned work
        assert gw0_tests.count("groupA") == 5
        assert gw0_tests.count("groupB") == 0
        # there is only groupB tests in gw1's assigned work
        assert gw1_tests.count("groupA") == 0
        assert gw1_tests.count("groupB") == 5
        # the third worker node recieved no work groups
        assert "gw2" not in groupings.keys()
        # all tests passed
        assert len(groupings["gw0"]) == 5
        assert len(groupings["gw1"]) == 5
        assert [group[1] for group in groupings["gw0"]].count("PASSED") == 5
        assert [group[1] for group in groupings["gw1"]].count("PASSED") == 5

    def test_default_distribution_fallback(self, testdir):
        testdir.makeconftest(
            """
            import pytest

            def pytest_xdist_set_test_group_from_nodeid(nodeid):
                group_names = ['groupA', 'groupB']
                nodeid_params = nodeid.split('[', 1)[-1].rstrip(']').split('-')
                for name in group_names:
                    if name in nodeid_params:
                        return name
        """
        )
        testdir.makepyfile(
            """
            import pytest
            @pytest.fixture(params=["groupA", "groupB"])
            def group(request):
                return request.param
            @pytest.fixture(params=[1, 2, 3, 4, 5])
            def number(request):
                return request.param
            def test_with_group(number, group): pass
            def test_no_group_no_class(number): pass
            class TestNoGroupClass:
                def test_no_group_class(self, number): pass
            class TestOtherNoGroupClass:
                def test_no_group_other_class(self, number): pass
        """
        )
        results = testdir.runpytest("-n3", "-v", "--dist=loadfile")
        combos = parse_tests_and_workers_from_output(results.outlines)
        groupings = {}
        for worker_id, status, nodeid in combos:
            groupings.setdefault(worker_id, []).append((nodeid, status))
        gw0_tests = "".join(group[0] for group in groupings["gw0"])
        gw1_tests = "".join(group[0] for group in groupings["gw1"])
        gw2_tests = "".join(group[0] for group in groupings["gw2"])
        # there is only groupA tests in gw0's assigned work
        assert gw0_tests.count("groupA") == 5
        assert gw0_tests.count("groupB") == 0
        # there is only groupB tests in gw1's assigned work
        assert gw1_tests.count("groupA") == 0
        assert gw1_tests.count("groupB") == 5
        # the third worker node recieved all remaining tests
        assert gw2_tests.count("test_no_group_no_class") == 5
        assert gw2_tests.count("test_no_group_class") == 5
        assert gw2_tests.count("test_no_group_other_class") == 5
        # all tests passed
        assert len(groupings["gw0"]) == 5
        assert len(groupings["gw1"]) == 5
        assert len(groupings["gw2"]) == 15
        assert [group[1] for group in groupings["gw0"]].count("PASSED") == 5
        assert [group[1] for group in groupings["gw1"]].count("PASSED") == 5
        assert [group[1] for group in groupings["gw2"]].count("PASSED") == 15


class TestSetTestGroupWithLoadSchedulerOrderGroups:

    def test_gw0_contains_group_b_and_gw1_contains_group_a(self, testdir):
        testdir.makeconftest(
            """
            import pytest

            def pytest_xdist_set_test_group_from_nodeid(nodeid):
                group_names = ['groupA', 'groupB']
                nodeid_params = nodeid.split('[', 1)[-1].rstrip(']').split('-')
                for name in group_names:
                    if name in nodeid_params:
                        return name

            def pytest_xdist_order_test_groups(workqueue):
                workqueue.move_to_end('groupA')
        """
        )
        testdir.makepyfile(
            """
            import pytest
            @pytest.fixture(params=["groupA", "groupB"])
            def group(request):
                return request.param
            @pytest.fixture(params=[1, 2, 3, 4, 5])
            def number(request):
                return request.param
            def test_with_group(number, group): pass
        """
        )
        results = testdir.runpytest("-n3", "-v")
        combos = parse_tests_and_workers_from_output(results.outlines)
        groupings = {}
        for worker_id, status, nodeid in combos:
            groupings.setdefault(worker_id, []).append((nodeid, status))
        gw0_tests = "".join(group[0] for group in groupings["gw0"])
        gw1_tests = "".join(group[0] for group in groupings["gw1"])
        # there is only groupB tests in gw0's assigned work
        assert gw0_tests.count("groupB") == 5
        assert gw0_tests.count("groupA") == 0
        # there is only groupA tests in gw1's assigned work
        assert gw1_tests.count("groupB") == 0
        assert gw1_tests.count("groupA") == 5
        # the third worker node recieved no work groups
        assert "gw2" not in groupings.keys()
        # all tests passed
        assert len(groupings["gw0"]) == 5
        assert len(groupings["gw1"]) == 5
        assert [group[1] for group in groupings["gw0"]].count("PASSED") == 5
        assert [group[1] for group in groupings["gw1"]].count("PASSED") == 5


def parse_tests_and_workers_from_output(lines):
    result = []
    for line in lines:
        # example match: "[gw0] PASSED test_a.py::test[7]"
        m = re.match(
            r"""
            \[(gw\d)\]  # worker
            \s*
            (?:\[\s*\d+%\])? # progress indicator (pytest >=3.3)
            \s(.*?)     # status string ("PASSED")
            \s(.*::.*)  # nodeid
        """,
            line.strip(),
            re.VERBOSE,
        )
        if m:
            worker, status, nodeid = m.groups()
            result.append((worker, status, nodeid))
    return result

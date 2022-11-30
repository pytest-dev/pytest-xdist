import os
import re
import shutil
from typing import Dict
from typing import List
from typing import Tuple

import pytest
import xdist


class TestDistribution:
    def test_n1_pass(self, pytester: pytest.Pytester) -> None:
        p1 = pytester.makepyfile(
            """
            def test_ok():
                pass
        """
        )
        result = pytester.runpytest(p1, "-n1")
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*1 passed*"])

    def test_n1_fail(self, pytester: pytest.Pytester) -> None:
        p1 = pytester.makepyfile(
            """
            def test_fail():
                assert 0
        """
        )
        result = pytester.runpytest(p1, "-n1")
        assert result.ret == 1
        result.stdout.fnmatch_lines(["*1 failed*"])

    def test_n1_import_error(self, pytester: pytest.Pytester) -> None:
        p1 = pytester.makepyfile(
            """
            import __import_of_missing_module
            def test_import():
                pass
        """
        )
        result = pytester.runpytest(p1, "-n1")
        assert result.ret == 1
        result.stdout.fnmatch_lines(
            ["E   *Error: No module named *__import_of_missing_module*"]
        )

    def test_n2_import_error(self, pytester: pytest.Pytester) -> None:
        """Check that we don't report the same import error multiple times
        in distributed mode."""
        p1 = pytester.makepyfile(
            """
            import __import_of_missing_module
            def test_import():
                pass
        """
        )
        result1 = pytester.runpytest(p1, "-n2")
        result2 = pytester.runpytest(p1, "-n1")
        assert len(result1.stdout.lines) == len(result2.stdout.lines)

    def test_n1_skip(self, pytester: pytest.Pytester) -> None:
        p1 = pytester.makepyfile(
            """
            def test_skip():
                import pytest
                pytest.skip("myreason")
        """
        )
        result = pytester.runpytest(p1, "-n1")
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*1 skipped*"])

    def test_manytests_to_one_import_error(self, pytester: pytest.Pytester) -> None:
        p1 = pytester.makepyfile(
            """
            import __import_of_missing_module
            def test_import():
                pass
        """
        )
        result = pytester.runpytest(p1, "--tx=popen", "--tx=popen")
        assert result.ret in (1, 2)
        result.stdout.fnmatch_lines(
            ["E   *Error: No module named *__import_of_missing_module*"]
        )

    def test_manytests_to_one_popen(self, pytester: pytest.Pytester) -> None:
        p1 = pytester.makepyfile(
            """
                import pytest
                def test_fail0():
                    assert 0
                def test_fail1():
                    raise ValueError()
                def test_ok():
                    pass
                def test_skip():
                    pytest.skip("hello")
            """
        )
        result = pytester.runpytest(p1, "-v", "-d", "--tx=popen", "--tx=popen")
        result.stdout.fnmatch_lines(["*1*Python*", "*2 failed, 1 passed, 1 skipped*"])
        assert result.ret == 1

    def test_n1_fail_minus_x(self, pytester: pytest.Pytester) -> None:
        p1 = pytester.makepyfile(
            """
            def test_fail1():
                assert 0
            def test_fail2():
                assert 0
        """
        )
        result = pytester.runpytest(p1, "-x", "-v", "-n1")
        assert result.ret == 2
        result.stdout.fnmatch_lines(["*Interrupted: stopping*1*", "*1 failed*"])

    def test_basetemp_in_subprocesses(self, pytester: pytest.Pytester) -> None:
        p1 = pytester.makepyfile(
            """
            def test_send(tmp_path):
                from pathlib import Path
                assert tmp_path.relative_to(Path(%r)), tmp_path
        """
            % str(pytester.path)
        )
        result = pytester.runpytest_subprocess(p1, "-n1")
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*1 passed*"])

    def test_dist_ini_specified(self, pytester: pytest.Pytester) -> None:
        p1 = pytester.makepyfile(
            """
                import pytest
                def test_fail0():
                    assert 0
                def test_fail1():
                    raise ValueError()
                def test_ok():
                    pass
                def test_skip():
                    pytest.skip("hello")
            """
        )
        pytester.makeini(
            """
            [pytest]
            addopts = --tx=3*popen
        """
        )
        result = pytester.runpytest(p1, "-d", "-v")
        result.stdout.fnmatch_lines(["*2*Python*", "*2 failed, 1 passed, 1 skipped*"])
        assert result.ret == 1

    def test_dist_tests_with_crash(self, pytester: pytest.Pytester) -> None:
        if not hasattr(os, "kill"):
            pytest.skip("no os.kill")

        p1 = pytester.makepyfile(
            """
                import pytest
                def test_fail0():
                    assert 0
                def test_fail1():
                    raise ValueError()
                def test_ok():
                    pass
                def test_skip():
                    pytest.skip("hello")
                def test_crash():
                    import time
                    import os
                    time.sleep(0.5)
                    os.kill(os.getpid(), 15)
            """
        )
        result = pytester.runpytest(p1, "-v", "-d", "-n1")
        result.stdout.fnmatch_lines(
            [
                "*Python*",
                "*PASS**test_ok*",
                "*node*down*",
                "*3 failed, 1 passed, 1 skipped*",
            ]
        )
        assert result.ret == 1

    def test_distribution_rsyncdirs_example(
        self, pytester: pytest.Pytester, monkeypatch
    ) -> None:
        # use a custom plugin that has a custom command-line option to ensure
        # this is propagated to workers (see #491)
        pytester.makepyfile(
            **{
                "myplugin/src/foobarplugin.py": """
            from __future__ import print_function

            import os
            import sys
            import pytest

            def pytest_addoption(parser):
                parser.addoption("--foobar", action="store", dest="foobar_opt")

            @pytest.hookimpl(tryfirst=True)
            def pytest_load_initial_conftests(early_config):
                opt = early_config.known_args_namespace.foobar_opt
                print("--foobar=%s active! [%s]" % (opt, os.getpid()), file=sys.stderr)
            """
            }
        )
        assert (pytester.path / "myplugin/src/foobarplugin.py").is_file()
        monkeypatch.setenv(
            "PYTHONPATH", str(pytester.path / "myplugin/src"), prepend=os.pathsep
        )

        source = pytester.mkdir("source")
        dest = pytester.mkdir("dest")
        subdir = source / "example_pkg"
        subdir.mkdir()
        subdir.joinpath("__init__.py").touch()
        p = subdir / "test_one.py"
        p.write_text("def test_5():\n  assert not __file__.startswith(%r)" % str(p))
        result = pytester.runpytest_subprocess(
            "-v",
            "-d",
            "-s",
            "-pfoobarplugin",
            "--foobar=123",
            "--dist=load",
            "--rsyncdir=%(subdir)s" % locals(),
            "--tx=popen//chdir=%(dest)s" % locals(),
            p,
        )
        assert result.ret == 0
        result.stdout.fnmatch_lines(
            [
                "*0* *cwd*",
                # "RSyncStart: [G1]",
                # "RSyncFinished: [G1]",
                "*1 passed*",
            ]
        )
        result.stderr.fnmatch_lines(["--foobar=123 active! *"])
        assert dest.joinpath(subdir.name).is_dir()

    def test_data_exchange(self, pytester: pytest.Pytester) -> None:
        pytester.makeconftest(
            """
            # This hook only called on the controlling process.
            def pytest_configure_node(node):
                node.workerinput['a'] = 42
                node.workerinput['b'] = 7

            def pytest_configure(config):
                # this attribute is only set on workers
                if hasattr(config, 'workerinput'):
                    a = config.workerinput['a']
                    b = config.workerinput['b']
                    r = a + b
                    config.workeroutput['r'] = r

            # This hook only called on the controlling process.
            def pytest_testnodedown(node, error):
                node.config.calc_result = node.workeroutput['r']

            def pytest_terminal_summary(terminalreporter):
                if not hasattr(terminalreporter.config, 'workerinput'):
                    calc_result = terminalreporter.config.calc_result
                    terminalreporter._tw.sep('-',
                        'calculated result is %s' % calc_result)
        """
        )
        p1 = pytester.makepyfile("def test_func(): pass")
        result = pytester.runpytest("-v", p1, "-d", "--tx=popen")
        result.stdout.fnmatch_lines(
            ["*0*Python*", "*calculated result is 49*", "*1 passed*"]
        )
        assert result.ret == 0

    def test_keyboardinterrupt_hooks_issue79(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(
            __init__="",
            test_one="""
            def test_hello():
                raise KeyboardInterrupt()
        """,
        )
        pytester.makeconftest(
            """
            def pytest_sessionfinish(session):
                # on the worker
                if hasattr(session.config, 'workeroutput'):
                    session.config.workeroutput['s2'] = 42
            # on the controller
            def pytest_testnodedown(node, error):
                assert node.workeroutput['s2'] == 42
                print ("s2call-finished")
        """
        )
        args = ["-n1", "--debug"]
        result = pytester.runpytest_subprocess(*args)
        s = result.stdout.str()
        assert result.ret == 2
        assert "s2call" in s
        assert "Interrupted" in s

    def test_keyboard_interrupt_dist(self, pytester: pytest.Pytester) -> None:
        # xxx could be refined to check for return code
        pytester.makepyfile(
            """
            def test_sleep():
                import time
                time.sleep(10)
        """
        )
        child = pytester.spawn_pytest("-n1 -v", expect_timeout=30.0)
        child.expect(".*test_sleep.*")
        child.kill(2)  # keyboard interrupt
        child.expect(".*KeyboardInterrupt.*")
        # child.expect(".*seconds.*")
        child.close()
        # assert ret == 2

    def test_dist_with_collectonly(self, pytester: pytest.Pytester) -> None:
        p1 = pytester.makepyfile(
            """
            def test_ok():
                pass
        """
        )
        result = pytester.runpytest(p1, "-n1", "--collect-only")
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*collected 1 item*"])


class TestDistEach:
    def test_simple(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(
            """
            def test_hello():
                pass
        """
        )
        result = pytester.runpytest_subprocess("--debug", "--dist=each", "--tx=2*popen")
        assert not result.ret
        result.stdout.fnmatch_lines(["*2 pass*"])

    @pytest.mark.xfail(
        run=False, reason="other python versions might not have pytest installed"
    )
    def test_simple_diffoutput(self, pytester: pytest.Pytester) -> None:
        interpreters = []
        for name in ("python2.5", "python2.6"):
            interp = shutil.which(name)
            if interp is None:
                pytest.skip("%s not found" % name)
            interpreters.append(interp)

        pytester.makepyfile(
            __init__="",
            test_one="""
            import sys
            def test_hello():
                print("%s...%s" % sys.version_info[:2])
                assert 0
        """,
        )
        args = ["--dist=each", "-v"]
        args += ["--tx", "popen//python=%s" % interpreters[0]]
        args += ["--tx", "popen//python=%s" % interpreters[1]]
        result = pytester.runpytest(*args)
        s = result.stdout.str()
        assert "2...5" in s
        assert "2...6" in s


class TestTerminalReporting:
    @pytest.mark.parametrize("verbosity", ["", "-q", "-v"])
    def test_output_verbosity(self, pytester, verbosity: str) -> None:
        pytester.makepyfile(
            """
            def test_ok():
                pass
        """
        )
        args = ["-n1"]
        if verbosity:
            args.append(verbosity)
        result = pytester.runpytest(*args)
        out = result.stdout.str()
        if verbosity == "-v":
            assert "scheduling tests" in out
            assert "gw" in out
        elif verbosity == "-q":
            assert "scheduling tests" not in out
            assert "gw" not in out
            assert "bringing up nodes..." in out
        else:
            assert "scheduling tests" not in out
            assert "gw" in out

    def test_pass_skip_fail(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(
            """
            import pytest
            def test_ok():
                pass
            def test_skip():
                pytest.skip("xx")
            def test_func():
                assert 0
        """
        )
        result = pytester.runpytest("-n1", "-v")
        result.stdout.fnmatch_lines_random(
            [
                "*PASS*test_pass_skip_fail.py*test_ok*",
                "*SKIP*test_pass_skip_fail.py*test_skip*",
                "*FAIL*test_pass_skip_fail.py*test_func*",
            ]
        )
        result.stdout.fnmatch_lines(
            ["*def test_func():", ">       assert 0", "E       assert 0"]
        )

    def test_fail_platinfo(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(
            """
            def test_func():
                assert 0
        """
        )
        result = pytester.runpytest("-n1", "-v")
        result.stdout.fnmatch_lines(
            [
                "*FAIL*test_fail_platinfo.py*test_func*",
                "*0*Python*",
                "*def test_func():",
                ">       assert 0",
                "E       assert 0",
            ]
        )

    def test_logfinish_hook(self, pytester: pytest.Pytester) -> None:
        """Ensure the pytest_runtest_logfinish hook is being properly handled"""
        pytester.makeconftest(
            """
            def pytest_runtest_logfinish():
                print('pytest_runtest_logfinish hook called')
        """
        )
        pytester.makepyfile(
            """
            def test_func():
                pass
        """
        )
        result = pytester.runpytest("-n1", "-s")
        result.stdout.fnmatch_lines(["*pytest_runtest_logfinish hook called*"])


def test_teardownfails_one_function(pytester: pytest.Pytester) -> None:
    p = pytester.makepyfile(
        """
        def test_func():
            pass
        def teardown_function(function):
            assert 0
    """
    )
    result = pytester.runpytest(p, "-n1", "--tx=popen")
    result.stdout.fnmatch_lines(
        ["*def teardown_function(function):*", "*1 passed*1 error*"]
    )


@pytest.mark.xfail
def test_terminate_on_hangingnode(pytester: pytest.Pytester) -> None:
    p = pytester.makeconftest(
        """
        def pytest_sessionfinish(session):
            if session.nodeid == "my": # running on worker
                import time
                time.sleep(3)
    """
    )
    result = pytester.runpytest(p, "--dist=each", "--tx=popen//id=my")
    assert result.duration < 2.0
    result.stdout.fnmatch_lines(["*killed*my*"])


@pytest.mark.xfail(reason="works if run outside test suite", run=False)
def test_session_hooks(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        """
        import sys
        def pytest_sessionstart(session):
            sys.pytestsessionhooks = session
        def pytest_sessionfinish(session):
            if hasattr(session.config, 'workerinput'):
                name = "worker"
            else:
                name = "controller"
            with open(name, "w") as f:
                f.write("xy")
            # let's fail on the worker
            if name == "worker":
                raise ValueError(42)
    """
    )
    p = pytester.makepyfile(
        """
        import sys
        def test_hello():
            assert hasattr(sys, 'pytestsessionhooks')
    """
    )
    result = pytester.runpytest(p, "--dist=each", "--tx=popen")
    result.stdout.fnmatch_lines(["*ValueError*", "*1 passed*"])
    assert not result.ret
    d = result.parseoutcomes()
    assert d["passed"] == 1
    assert pytester.path.joinpath("worker").exists()
    assert pytester.path.joinpath("controller").exists()


def test_session_testscollected(pytester: pytest.Pytester) -> None:
    """
    Make sure controller node is updating the session object with the number
    of tests collected from the workers.
    """
    pytester.makepyfile(
        test_foo="""
        import pytest
        @pytest.mark.parametrize('i', range(3))
        def test_ok(i):
            pass
    """
    )
    pytester.makeconftest(
        """
        def pytest_sessionfinish(session):
            collected = getattr(session, 'testscollected', None)
            with open('testscollected', 'w') as f:
                f.write('collected = %s' % collected)
    """
    )
    result = pytester.inline_run("-n1")
    result.assertoutcome(passed=3)
    collected_file = pytester.path / "testscollected"
    assert collected_file.is_file()
    assert collected_file.read_text() == "collected = 3"


def test_fixture_teardown_failure(pytester: pytest.Pytester) -> None:
    p = pytester.makepyfile(
        """
        import pytest
        @pytest.fixture(scope="module")
        def myarg(request):
            yield 42
            raise ValueError(42)

        def test_hello(myarg):
            pass
    """
    )
    result = pytester.runpytest_subprocess(p, "-n1")
    result.stdout.fnmatch_lines(["*ValueError*42*", "*1 passed*1 error*"])
    assert result.ret


def test_config_initialization(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, pytestconfig
) -> None:
    """Ensure workers and controller are initialized consistently. Integration test for #445"""
    pytester.makepyfile(
        **{
            "dir_a/test_foo.py": """
                def test_1(request):
                    assert request.config.option.verbose == 2
        """
        }
    )
    pytester.makefile(
        ".ini",
        myconfig="""
        [pytest]
        testpaths=dir_a
    """,
    )
    monkeypatch.setenv("PYTEST_ADDOPTS", "-v")
    result = pytester.runpytest("-n2", "-c", "myconfig.ini", "-v")
    result.stdout.fnmatch_lines(["dir_a/test_foo.py::test_1*", "*= 1 passed in *"])
    assert result.ret == 0


@pytest.mark.parametrize("when", ["setup", "call", "teardown"])
def test_crashing_item(pytester, when) -> None:
    """Ensure crashing item is correctly reported during all testing stages"""
    code = dict(setup="", call="", teardown="")
    code[when] = "os._exit(1)"
    p = pytester.makepyfile(
        """
        import os
        import pytest

        @pytest.fixture
        def fix():
            {setup}
            yield
            {teardown}

        def test_crash(fix):
            {call}
            pass

        def test_ok():
            pass
    """.format(
            **code
        )
    )
    passes = 2 if when == "teardown" else 1
    result = pytester.runpytest("-n2", p)
    result.stdout.fnmatch_lines(
        ["*crashed*test_crash*", "*1 failed*%d passed*" % passes]
    )


def test_multiple_log_reports(pytester: pytest.Pytester) -> None:
    """
    Ensure that pytest-xdist supports plugins that emit multiple logreports
    (#206).
    Inspired by pytest-rerunfailures.
    """
    pytester.makeconftest(
        """
        from _pytest.runner import runtestprotocol
        def pytest_runtest_protocol(item, nextitem):
            item.ihook.pytest_runtest_logstart(nodeid=item.nodeid,
                                               location=item.location)
            reports = runtestprotocol(item, nextitem=nextitem)
            for report in reports:
                item.ihook.pytest_runtest_logreport(report=report)
            return True
    """
    )
    pytester.makepyfile(
        """
        def test():
            pass
    """
    )
    result = pytester.runpytest("-n1")
    result.stdout.fnmatch_lines(["*2 passed*"])


def test_skipping(pytester: pytest.Pytester) -> None:
    p = pytester.makepyfile(
        """
        import pytest
        def test_crash():
            pytest.skip("hello")
    """
    )
    result = pytester.runpytest("-n1", "-rs", p)
    assert result.ret == 0
    result.stdout.fnmatch_lines(["*hello*", "*1 skipped*"])


def test_fixture_scope_caching_issue503(pytester: pytest.Pytester) -> None:
    p1 = pytester.makepyfile(
        """
            import pytest

            @pytest.fixture(scope='session')
            def fix():
                assert fix.counter == 0, \
                    'session fixture was invoked multiple times'
                fix.counter += 1
            fix.counter = 0

            def test_a(fix):
                pass

            def test_b(fix):
                pass
    """
    )
    result = pytester.runpytest(p1, "-v", "-n1")
    assert result.ret == 0
    result.stdout.fnmatch_lines(["*2 passed*"])


def test_issue_594_random_parametrize(pytester: pytest.Pytester) -> None:
    """
    Make sure that tests that are randomly parametrized display an appropriate
    error message, instead of silently skipping the entire test run.
    """
    p1 = pytester.makepyfile(
        """
        import pytest
        import random

        xs = list(range(10))
        random.shuffle(xs)
        @pytest.mark.parametrize('x', xs)
        def test_foo(x):
            assert 1
    """
    )
    result = pytester.runpytest(p1, "-v", "-n4")
    assert result.ret == 1
    result.stdout.fnmatch_lines(["Different tests were collected between gw* and gw*"])


def test_tmpdir_disabled(pytester: pytest.Pytester) -> None:
    """Test xdist doesn't break if internal tmpdir plugin is disabled (#22)."""
    p1 = pytester.makepyfile(
        """
        def test_ok():
            pass
    """
    )
    result = pytester.runpytest(p1, "-n1", "-p", "no:tmpdir")
    assert result.ret == 0
    result.stdout.fnmatch_lines("*1 passed*")


@pytest.mark.parametrize("plugin", ["xdist.looponfail"])
def test_sub_plugins_disabled(pytester, plugin) -> None:
    """Test that xdist doesn't break if we disable any of its sub-plugins. (#32)"""
    p1 = pytester.makepyfile(
        """
        def test_ok():
            pass
    """
    )
    result = pytester.runpytest(p1, "-n1", "-p", f"no:{plugin}")
    assert result.ret == 0
    result.stdout.fnmatch_lines("*1 passed*")


class TestWarnings:
    @pytest.mark.parametrize("n", ["-n0", "-n1"])
    def test_warnings(self, pytester, n) -> None:
        pytester.makepyfile(
            """
            import warnings, py, pytest

            @pytest.mark.filterwarnings('ignore:config.warn has been deprecated')
            def test_func(request):
                warnings.warn(UserWarning('this is a warning'))
            """
        )
        result = pytester.runpytest(n)
        result.stdout.fnmatch_lines(["*this is a warning*", "*1 passed, 1 warning*"])

    def test_warning_captured_deprecated_in_pytest_6(
        self, pytester: pytest.Pytester
    ) -> None:
        """
        Do not trigger the deprecated pytest_warning_captured hook in pytest 6+ (#562)
        """
        from _pytest import hookspec

        if not hasattr(hookspec, "pytest_warning_captured"):
            pytest.skip(
                f"pytest {pytest.__version__} does not have the pytest_warning_captured hook."
            )

        pytester.makeconftest(
            """
            def pytest_warning_captured(warning_message):
                if warning_message == "my custom worker warning":
                    assert False, (
                        "this hook should not be called from workers "
                        "in this version: {}"
                    ).format(warning_message)
        """
        )
        pytester.makepyfile(
            """
            import warnings
            def test():
                warnings.warn("my custom worker warning")
        """
        )
        result = pytester.runpytest("-n1", "-Wignore")
        result.stdout.fnmatch_lines(["*1 passed*"])
        result.stdout.no_fnmatch_line("*this hook should not be called in this version")

    @pytest.mark.parametrize("n", ["-n0", "-n1"])
    def test_custom_subclass(self, pytester, n) -> None:
        """Check that warning subclasses that don't honor the args attribute don't break
        pytest-xdist (#344)
        """
        pytester.makepyfile(
            """
            import warnings, py, pytest

            class MyWarning(UserWarning):

                def __init__(self, p1, p2):
                    self.p1 = p1
                    self.p2 = p2
                    self.args = ()

            def test_func(request):
                warnings.warn(MyWarning("foo", 1))
        """
        )
        pytester.syspathinsert()
        result = pytester.runpytest(n)
        result.stdout.fnmatch_lines(["*MyWarning*", "*1 passed, 1 warning*"])

    @pytest.mark.parametrize("n", ["-n0", "-n1"])
    def test_unserializable_arguments(self, pytester, n) -> None:
        """Check that warnings with unserializable arguments are handled correctly (#349)."""
        pytester.makepyfile(
            """
            import warnings, pytest

            def test_func(tmp_path):
                fn = tmp_path / 'foo.txt'
                fn.touch()
                with fn.open('r') as f:
                    warnings.warn(UserWarning("foo", f))
        """
        )
        pytester.syspathinsert()
        result = pytester.runpytest(n)
        result.stdout.fnmatch_lines(["*UserWarning*foo.txt*", "*1 passed, 1 warning*"])

    @pytest.mark.parametrize("n", ["-n0", "-n1"])
    def test_unserializable_warning_details(self, pytester, n) -> None:
        """Check that warnings with unserializable _WARNING_DETAILS are
        handled correctly (#379).
        """
        pytester.makepyfile(
            """
            import warnings, pytest
            import socket
            import gc
            def abuse_socket():
                s = socket.socket()
                del s

            # Deliberately provoke a ResourceWarning for an unclosed socket.
            # The socket itself will end up attached as a value in
            # _WARNING_DETAIL. We need to test that it is not serialized
            # (it can't be, so the test will fail if we try to).
            @pytest.mark.filterwarnings('always')
            def test_func(tmp_path):
                abuse_socket()
                gc.collect()
        """
        )
        pytester.syspathinsert()
        result = pytester.runpytest(n)
        result.stdout.fnmatch_lines(
            ["*ResourceWarning*unclosed*", "*1 passed, 1 warning*"]
        )


class TestNodeFailure:
    def test_load_single(self, pytester: pytest.Pytester) -> None:
        f = pytester.makepyfile(
            """
            import os
            def test_a(): os._exit(1)
            def test_b(): pass
        """
        )
        res = pytester.runpytest(f, "-n1")
        res.stdout.fnmatch_lines(
            [
                "replacing crashed worker gw*",
                "worker*crashed while running*",
                "*1 failed*1 passed*",
            ]
        )

    def test_load_multiple(self, pytester: pytest.Pytester) -> None:
        f = pytester.makepyfile(
            """
            import os
            def test_a(): pass
            def test_b(): os._exit(1)
            def test_c(): pass
            def test_d(): pass
        """
        )
        res = pytester.runpytest(f, "-n2")
        res.stdout.fnmatch_lines(
            [
                "replacing crashed worker gw*",
                "worker*crashed while running*",
                "*1 failed*3 passed*",
            ]
        )

    def test_each_single(self, pytester: pytest.Pytester) -> None:
        f = pytester.makepyfile(
            """
            import os
            def test_a(): os._exit(1)
            def test_b(): pass
        """
        )
        res = pytester.runpytest(f, "--dist=each", "--tx=popen")
        res.stdout.fnmatch_lines(
            [
                "replacing crashed worker gw*",
                "worker*crashed while running*",
                "*1 failed*1 passed*",
            ]
        )

    @pytest.mark.xfail(reason="#20: xdist race condition on node restart")
    def test_each_multiple(self, pytester: pytest.Pytester) -> None:
        f = pytester.makepyfile(
            """
            import os
            def test_a(): os._exit(1)
            def test_b(): pass
        """
        )
        res = pytester.runpytest(f, "--dist=each", "--tx=2*popen")
        res.stdout.fnmatch_lines(
            [
                "*Replacing crashed worker*",
                "*Worker*crashed while running*",
                "*2 failed*2 passed*",
            ]
        )

    def test_max_worker_restart(self, pytester: pytest.Pytester) -> None:
        f = pytester.makepyfile(
            """
            import os
            def test_a(): pass
            def test_b(): os._exit(1)
            def test_c(): os._exit(1)
            def test_d(): pass
        """
        )
        res = pytester.runpytest(f, "-n4", "--max-worker-restart=1")
        res.stdout.fnmatch_lines(
            [
                "replacing crashed worker*",
                "maximum crashed workers reached: 1*",
                "worker*crashed while running*",
                "worker*crashed while running*",
                "*2 failed*2 passed*",
            ]
        )

    def test_max_worker_restart_tests_queued(self, pytester: pytest.Pytester) -> None:
        f = pytester.makepyfile(
            """
            import os, pytest
            @pytest.mark.parametrize('i', range(10))
            def test(i): os._exit(1)
        """
        )
        res = pytester.runpytest(f, "-n2", "--max-worker-restart=3")
        res.stdout.fnmatch_lines(
            [
                "replacing crashed worker*",
                "maximum crashed workers reached: 3*",
                "worker*crashed while running*",
                "worker*crashed while running*",
                "* xdist: maximum crashed workers reached: 3 *",
                "* 4 failed in *",
            ]
        )
        assert "INTERNALERROR" not in res.stdout.str()

    def test_max_worker_restart_die(self, pytester: pytest.Pytester) -> None:
        f = pytester.makepyfile(
            """
            import os
            os._exit(1)
        """
        )
        res = pytester.runpytest(f, "-n4", "--max-worker-restart=0")
        res.stdout.fnmatch_lines(
            [
                "* xdist: worker gw* crashed and worker restarting disabled *",
                "* no tests ran in *",
            ]
        )

    def test_disable_restart(self, pytester: pytest.Pytester) -> None:
        f = pytester.makepyfile(
            """
            import os
            def test_a(): pass
            def test_b(): os._exit(1)
            def test_c(): pass
        """
        )
        res = pytester.runpytest(f, "-n4", "--max-worker-restart=0")
        res.stdout.fnmatch_lines(
            [
                "worker gw* crashed and worker restarting disabled",
                "*worker*crashed while running*",
                "* xdist: worker gw* crashed and worker restarting disabled *",
                "* 1 failed, 2 passed in *",
            ]
        )


@pytest.mark.parametrize("n", [0, 2])
def test_worker_id_fixture(pytester, n) -> None:
    import glob

    f = pytester.makepyfile(
        """
        import pytest
        @pytest.mark.parametrize("run_num", range(2))
        def test_worker_id1(worker_id, run_num):
            with open("worker_id%s.txt" % run_num, "w") as f:
                f.write(worker_id)
    """
    )
    result = pytester.runpytest(f, "-n%d" % n)
    result.stdout.fnmatch_lines("* 2 passed in *")
    worker_ids = set()
    for fname in glob.glob(str(pytester.path / "*.txt")):
        with open(fname) as f:
            worker_ids.add(f.read().strip())
    if n == 0:
        assert worker_ids == {"master"}
    else:
        assert worker_ids == {"gw0", "gw1"}


@pytest.mark.parametrize("n", [0, 2])
def test_testrun_uid_fixture(pytester, n) -> None:
    import glob

    f = pytester.makepyfile(
        """
        import pytest
        @pytest.mark.parametrize("run_num", range(2))
        def test_testrun_uid1(testrun_uid, run_num):
            with open("testrun_uid%s.txt" % run_num, "w") as f:
                f.write(testrun_uid)
    """
    )
    result = pytester.runpytest(f, "-n%d" % n)
    result.stdout.fnmatch_lines("* 2 passed in *")
    testrun_uids = set()
    for fname in glob.glob(str(pytester.path / "*.txt")):
        with open(fname) as f:
            testrun_uids.add(f.read().strip())
    assert len(testrun_uids) == 1
    assert len(testrun_uids.pop()) == 32


@pytest.mark.parametrize("tb", ["auto", "long", "short", "no", "line", "native"])
def test_error_report_styles(pytester, tb) -> None:
    pytester.makepyfile(
        """
        import pytest
        def test_error_report_styles():
            raise RuntimeError('some failure happened')
    """
    )
    result = pytester.runpytest("-n1", "--tb=%s" % tb)
    if tb != "no":
        result.stdout.fnmatch_lines("*some failure happened*")
    result.assert_outcomes(failed=1)


def test_color_yes_collection_on_non_atty(pytester, request) -> None:
    """skip collect progress report when working on non-terminals.

    Similar to pytest-dev/pytest#1397
    """
    tr = request.config.pluginmanager.getplugin("terminalreporter")
    if not hasattr(tr, "isatty"):
        pytest.skip("only valid for newer pytest versions")
    pytester.makepyfile(
        """
        import pytest
        @pytest.mark.parametrize('i', range(10))
        def test_this(i):
            assert 1
    """
    )
    args = ["--color=yes", "-n2"]
    result = pytester.runpytest(*args)
    assert "test session starts" in result.stdout.str()
    assert "\x1b[1m" in result.stdout.str()
    assert "gw0 [10] / gw1 [10]" in result.stdout.str()
    assert "gw0 C / gw1 C" not in result.stdout.str()


def test_without_terminal_plugin(pytester, request) -> None:
    """
    No output when terminal plugin is disabled
    """
    pytester.makepyfile(
        """
        def test_1():
            pass
    """
    )
    result = pytester.runpytest("-p", "no:terminal", "-n2")
    assert result.stdout.str() == ""
    assert result.stderr.str() == ""
    assert result.ret == 0


def test_internal_error_with_maxfail(pytester: pytest.Pytester) -> None:
    """
    Internal error when using --maxfail option (#62, #65).
    """
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture(params=['1', '2'])
        def crasher():
            raise RuntimeError

        def test_aaa0(crasher):
            pass
        def test_aaa1(crasher):
            pass
    """
    )
    result = pytester.runpytest_subprocess("--maxfail=1", "-n1")
    result.stdout.fnmatch_lines(["* 1 error in *"])
    assert "INTERNALERROR" not in result.stderr.str()


def test_internal_errors_propagate_to_controller(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        """
        def pytest_collection_modifyitems():
            raise RuntimeError("Some runtime error")
        """
    )
    pytester.makepyfile("def test(): pass")
    result = pytester.runpytest("-n1")
    result.stdout.fnmatch_lines(["*RuntimeError: Some runtime error*"])


class TestLoadScope:
    def test_by_module(self, pytester: pytest.Pytester) -> None:
        test_file = """
            import pytest
            @pytest.mark.parametrize('i', range(10))
            def test(i):
                pass
        """
        pytester.makepyfile(test_a=test_file, test_b=test_file)
        result = pytester.runpytest("-n2", "--dist=loadscope", "-v")
        assert get_workers_and_test_count_by_prefix(
            "test_a.py::test", result.outlines
        ) in ({"gw0": 10}, {"gw1": 10})
        assert get_workers_and_test_count_by_prefix(
            "test_b.py::test", result.outlines
        ) in ({"gw0": 10}, {"gw1": 10})

    def test_by_class(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(
            test_a="""
            import pytest
            class TestA:
                @pytest.mark.parametrize('i', range(10))
                def test(self, i):
                    pass

            class TestB:
                @pytest.mark.parametrize('i', range(10))
                def test(self, i):
                    pass
        """
        )
        result = pytester.runpytest("-n2", "--dist=loadscope", "-v")
        assert get_workers_and_test_count_by_prefix(
            "test_a.py::TestA", result.outlines
        ) in ({"gw0": 10}, {"gw1": 10})
        assert get_workers_and_test_count_by_prefix(
            "test_a.py::TestB", result.outlines
        ) in ({"gw0": 10}, {"gw1": 10})

    def test_module_single_start(self, pytester: pytest.Pytester) -> None:
        """Fix test suite never finishing in case all workers start with a single test (#277)."""
        test_file1 = """
            import pytest
            def test():
                pass
        """
        test_file2 = """
            import pytest
            def test_1():
                pass
            def test_2():
                pass
        """
        pytester.makepyfile(test_a=test_file1, test_b=test_file1, test_c=test_file2)
        result = pytester.runpytest("-n2", "--dist=loadscope", "-v")
        a = get_workers_and_test_count_by_prefix("test_a.py::test", result.outlines)
        b = get_workers_and_test_count_by_prefix("test_b.py::test", result.outlines)
        c1 = get_workers_and_test_count_by_prefix("test_c.py::test_1", result.outlines)
        c2 = get_workers_and_test_count_by_prefix("test_c.py::test_2", result.outlines)
        assert a in ({"gw0": 1}, {"gw1": 1})
        assert b in ({"gw0": 1}, {"gw1": 1})
        assert a.items() != b.items()
        assert c1 == c2


class TestFileScope:
    def test_by_module(self, pytester: pytest.Pytester) -> None:
        test_file = """
            import pytest
            class TestA:
                @pytest.mark.parametrize('i', range(10))
                def test(self, i):
                    pass

            class TestB:
                @pytest.mark.parametrize('i', range(10))
                def test(self, i):
                    pass
        """
        pytester.makepyfile(test_a=test_file, test_b=test_file)
        result = pytester.runpytest("-n2", "--dist=loadfile", "-v")
        test_a_workers_and_test_count = get_workers_and_test_count_by_prefix(
            "test_a.py::TestA", result.outlines
        )
        test_b_workers_and_test_count = get_workers_and_test_count_by_prefix(
            "test_b.py::TestB", result.outlines
        )

        assert test_a_workers_and_test_count in (
            {"gw0": 10},
            {"gw1": 0},
        ) or test_a_workers_and_test_count in ({"gw0": 0}, {"gw1": 10})
        assert test_b_workers_and_test_count in (
            {"gw0": 10},
            {"gw1": 0},
        ) or test_b_workers_and_test_count in ({"gw0": 0}, {"gw1": 10})

    def test_by_class(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(
            test_a="""
            import pytest
            class TestA:
                @pytest.mark.parametrize('i', range(10))
                def test(self, i):
                    pass

            class TestB:
                @pytest.mark.parametrize('i', range(10))
                def test(self, i):
                    pass
        """
        )
        result = pytester.runpytest("-n2", "--dist=loadfile", "-v")
        test_a_workers_and_test_count = get_workers_and_test_count_by_prefix(
            "test_a.py::TestA", result.outlines
        )
        test_b_workers_and_test_count = get_workers_and_test_count_by_prefix(
            "test_a.py::TestB", result.outlines
        )

        assert test_a_workers_and_test_count in (
            {"gw0": 10},
            {"gw1": 0},
        ) or test_a_workers_and_test_count in ({"gw0": 0}, {"gw1": 10})
        assert test_b_workers_and_test_count in (
            {"gw0": 10},
            {"gw1": 0},
        ) or test_b_workers_and_test_count in ({"gw0": 0}, {"gw1": 10})

    def test_module_single_start(self, pytester: pytest.Pytester) -> None:
        """Fix test suite never finishing in case all workers start with a single test (#277)."""
        test_file1 = """
            import pytest
            def test():
                pass
        """
        test_file2 = """
            import pytest
            def test_1():
                pass
            def test_2():
                pass
        """
        pytester.makepyfile(test_a=test_file1, test_b=test_file1, test_c=test_file2)
        result = pytester.runpytest("-n2", "--dist=loadfile", "-v")
        a = get_workers_and_test_count_by_prefix("test_a.py::test", result.outlines)
        b = get_workers_and_test_count_by_prefix("test_b.py::test", result.outlines)
        c1 = get_workers_and_test_count_by_prefix("test_c.py::test_1", result.outlines)
        c2 = get_workers_and_test_count_by_prefix("test_c.py::test_2", result.outlines)
        assert a in ({"gw0": 1}, {"gw1": 1})
        assert b in ({"gw0": 1}, {"gw1": 1})
        assert a.items() != b.items()
        assert c1 == c2


class TestGroupScope:
    def test_by_module(self, testdir):
        test_file = """
            import pytest
            class TestA:
                @pytest.mark.xdist_group(name="xdist_group")
                @pytest.mark.parametrize('i', range(5))
                def test(self, i):
                    pass
        """
        testdir.makepyfile(test_a=test_file, test_b=test_file)
        result = testdir.runpytest("-n2", "--dist=loadgroup", "-v")
        test_a_workers_and_test_count = get_workers_and_test_count_by_prefix(
            "test_a.py::TestA", result.outlines
        )
        test_b_workers_and_test_count = get_workers_and_test_count_by_prefix(
            "test_b.py::TestA", result.outlines
        )

        assert test_a_workers_and_test_count in (
            {"gw0": 5},
            {"gw1": 0},
        ) or test_a_workers_and_test_count in ({"gw0": 0}, {"gw1": 5})
        assert test_b_workers_and_test_count in (
            {"gw0": 5},
            {"gw1": 0},
        ) or test_b_workers_and_test_count in ({"gw0": 0}, {"gw1": 5})
        assert (
            test_a_workers_and_test_count.items()
            == test_b_workers_and_test_count.items()
        )

    def test_by_class(self, testdir):
        testdir.makepyfile(
            test_a="""
            import pytest
            class TestA:
                @pytest.mark.xdist_group(name="xdist_group")
                @pytest.mark.parametrize('i', range(10))
                def test(self, i):
                    pass
            class TestB:
                @pytest.mark.xdist_group(name="xdist_group")
                @pytest.mark.parametrize('i', range(10))
                def test(self, i):
                    pass
        """
        )
        result = testdir.runpytest("-n2", "--dist=loadgroup", "-v")
        test_a_workers_and_test_count = get_workers_and_test_count_by_prefix(
            "test_a.py::TestA", result.outlines
        )
        test_b_workers_and_test_count = get_workers_and_test_count_by_prefix(
            "test_a.py::TestB", result.outlines
        )

        assert test_a_workers_and_test_count in (
            {"gw0": 10},
            {"gw1": 0},
        ) or test_a_workers_and_test_count in ({"gw0": 0}, {"gw1": 10})
        assert test_b_workers_and_test_count in (
            {"gw0": 10},
            {"gw1": 0},
        ) or test_b_workers_and_test_count in ({"gw0": 0}, {"gw1": 10})
        assert (
            test_a_workers_and_test_count.items()
            == test_b_workers_and_test_count.items()
        )

    def test_module_single_start(self, testdir):
        test_file1 = """
            import pytest
            @pytest.mark.xdist_group(name="xdist_group")
            def test():
                pass
        """
        test_file2 = """
            import pytest
            def test_1():
                pass
            @pytest.mark.xdist_group(name="xdist_group")
            def test_2():
                pass
        """
        testdir.makepyfile(test_a=test_file1, test_b=test_file1, test_c=test_file2)
        result = testdir.runpytest("-n2", "--dist=loadgroup", "-v")
        a = get_workers_and_test_count_by_prefix("test_a.py::test", result.outlines)
        b = get_workers_and_test_count_by_prefix("test_b.py::test", result.outlines)
        c = get_workers_and_test_count_by_prefix("test_c.py::test_2", result.outlines)

        assert a.keys() == b.keys() and b.keys() == c.keys()

    def test_with_two_group_names(self, testdir):
        test_file = """
            import pytest
            @pytest.mark.xdist_group(name="group1")
            def test_1():
                pass
            @pytest.mark.xdist_group("group2")
            def test_2():
                pass
        """
        testdir.makepyfile(test_a=test_file, test_b=test_file)
        result = testdir.runpytest("-n2", "--dist=loadgroup", "-v")
        a_1 = get_workers_and_test_count_by_prefix("test_a.py::test_1", result.outlines)
        a_2 = get_workers_and_test_count_by_prefix("test_a.py::test_2", result.outlines)
        b_1 = get_workers_and_test_count_by_prefix("test_b.py::test_1", result.outlines)
        b_2 = get_workers_and_test_count_by_prefix("test_b.py::test_2", result.outlines)

        assert a_1.keys() == b_1.keys() and a_2.keys() == b_2.keys()


class TestLocking:
    _test_content = """
    class TestClassName%s(object):

        @classmethod
        def setup_class(cls):
            FILE_LOCK.acquire()

        @classmethod
        def teardown_class(cls):
            FILE_LOCK.release()

        def test_a(self):
            pass

        def test_b(self):
            pass

        def test_c(self):
            pass

    """

    test_file1 = """
    import filelock

    FILE_LOCK = filelock.FileLock("test.lock")

    """ + (
        (_test_content * 4) % ("A", "B", "C", "D")
    )

    @pytest.mark.parametrize("scope", ["each", "load", "loadscope", "loadfile", "no"])
    def test_single_file(self, pytester, scope) -> None:
        pytester.makepyfile(test_a=self.test_file1)
        result = pytester.runpytest("-n2", "--dist=%s" % scope, "-v")
        result.assert_outcomes(passed=(12 if scope != "each" else 12 * 2))

    @pytest.mark.parametrize("scope", ["each", "load", "loadscope", "loadfile", "no"])
    def test_multi_file(self, pytester, scope) -> None:
        pytester.makepyfile(
            test_a=self.test_file1,
            test_b=self.test_file1,
            test_c=self.test_file1,
            test_d=self.test_file1,
        )
        result = pytester.runpytest("-n2", "--dist=%s" % scope, "-v")
        result.assert_outcomes(passed=(48 if scope != "each" else 48 * 2))


def parse_tests_and_workers_from_output(lines: List[str]) -> List[Tuple[str, str, str]]:
    result = []
    for line in lines:
        # example match: "[gw0] PASSED test_a.py::test[7]"
        m = re.match(
            r"""
            \[(gw\d)\]  # worker
            \s*
            (?:\[\s*\d+%\])? # progress indicator
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


def get_workers_and_test_count_by_prefix(
    prefix: str, lines: List[str], expected_status: str = "PASSED"
) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for worker, status, nodeid in parse_tests_and_workers_from_output(lines):
        if expected_status == status and nodeid.startswith(prefix):
            result[worker] = result.get(worker, 0) + 1
    return result


class TestAPI:
    @pytest.fixture
    def fake_request(self):
        class FakeOption:
            def __init__(self):
                self.dist = "load"

        class FakeConfig:
            def __init__(self):
                self.workerinput = {"workerid": "gw5"}
                self.option = FakeOption()

        class FakeRequest:
            def __init__(self):
                self.config = FakeConfig()

        return FakeRequest()

    def test_is_xdist_worker(self, fake_request) -> None:
        assert xdist.is_xdist_worker(fake_request)
        del fake_request.config.workerinput
        assert not xdist.is_xdist_worker(fake_request)

    def test_is_xdist_controller(self, fake_request) -> None:
        assert not xdist.is_xdist_master(fake_request)
        assert not xdist.is_xdist_controller(fake_request)

        del fake_request.config.workerinput
        assert xdist.is_xdist_master(fake_request)
        assert xdist.is_xdist_controller(fake_request)

        fake_request.config.option.dist = "no"
        assert not xdist.is_xdist_master(fake_request)
        assert not xdist.is_xdist_controller(fake_request)

    def test_get_xdist_worker_id(self, fake_request) -> None:
        assert xdist.get_xdist_worker_id(fake_request) == "gw5"
        del fake_request.config.workerinput
        assert xdist.get_xdist_worker_id(fake_request) == "master"


def test_collection_crash(testdir):
    p1 = testdir.makepyfile(
        """
        assert 0
    """
    )
    result = testdir.runpytest(p1, "-n1")
    assert result.ret == 1
    result.stdout.fnmatch_lines(
        [
            "gw0 I",
            "gw0 [[]0[]]",
            "*_ ERROR collecting test_collection_crash.py _*",
            "E   assert 0",
            "*= 1 error in *",
        ]
    )


def test_dist_in_addopts(testdir):
    """Users can set a default distribution in the configuration file (#789)."""
    testdir.makepyfile(
        """
        def test():
            pass
        """
    )
    testdir.makeini(
        """
        [pytest]
        addopts = --dist loadscope
        """
    )
    result = testdir.runpytest()
    assert result.ret == 0

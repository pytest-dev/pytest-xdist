import py
import pytest


class TestDistribution:
    def test_n1_pass(self, testdir):
        p1 = testdir.makepyfile("""
            def test_ok():
                pass
        """)
        result = testdir.runpytest(p1, "-n1")
        assert result.ret == 0
        result.stdout.fnmatch_lines([
            "*1 passed*",
        ])

    def test_n1_fail(self, testdir):
        p1 = testdir.makepyfile("""
            def test_fail():
                assert 0
        """)
        result = testdir.runpytest(p1, "-n1")
        assert result.ret == 1
        result.stdout.fnmatch_lines([
            "*1 failed*",
        ])

    def test_n1_import_error(self, testdir):
        p1 = testdir.makepyfile("""
            import __import_of_missing_module
            def test_import():
                pass
        """)
        result = testdir.runpytest(p1, "-n1")
        assert result.ret == 1
        result.stdout.fnmatch_lines([
            "E   *Error: No module named *__import_of_missing_module*",
        ])

    def test_n2_import_error(self, testdir):
        """Check that we don't report the same import error multiple times
        in distributed mode."""
        p1 = testdir.makepyfile("""
            import __import_of_missing_module
            def test_import():
                pass
        """)
        result1 = testdir.runpytest(p1, "-n2")
        result2 = testdir.runpytest(p1, "-n1")
        assert len(result1.stdout.lines) == len(result2.stdout.lines)

    def test_n1_skip(self, testdir):
        p1 = testdir.makepyfile("""
            def test_skip():
                import py
                py.test.skip("myreason")
        """)
        result = testdir.runpytest(p1, "-n1")
        assert result.ret == 0
        result.stdout.fnmatch_lines([
            "*1 skipped*",
        ])

    def test_manytests_to_one_import_error(self, testdir):
        p1 = testdir.makepyfile("""
            import __import_of_missing_module
            def test_import():
                pass
        """)
        result = testdir.runpytest(p1, '--tx=popen', '--tx=popen')
        assert result.ret in (1, 2)
        result.stdout.fnmatch_lines([
            "E   *Error: No module named *__import_of_missing_module*",
        ])

    def test_manytests_to_one_popen(self, testdir):
        p1 = testdir.makepyfile(
            """
                import py
                def test_fail0():
                    assert 0
                def test_fail1():
                    raise ValueError()
                def test_ok():
                    pass
                def test_skip():
                    py.test.skip("hello")
            """, )
        result = testdir.runpytest(p1, "-v", '-d', '--tx=popen', '--tx=popen')
        result.stdout.fnmatch_lines([
            "*1*Python*",
            "*2 failed, 1 passed, 1 skipped*",
        ])
        assert result.ret == 1

    def test_n1_fail_minus_x(self, testdir):
        p1 = testdir.makepyfile("""
            def test_fail1():
                assert 0
            def test_fail2():
                assert 0
        """)
        result = testdir.runpytest(p1, "-x", "-v", "-n1")
        assert result.ret == 2
        result.stdout.fnmatch_lines([
            "*Interrupted: stopping*1*",
            "*1 failed*",
        ])

    def test_basetemp_in_subprocesses(self, testdir):
        p1 = testdir.makepyfile("""
            def test_send(tmpdir):
                import py
                assert tmpdir.relto(py.path.local(%r)), tmpdir
        """ % str(testdir.tmpdir))
        result = testdir.runpytest_subprocess(p1, "-n1")
        assert result.ret == 0
        result.stdout.fnmatch_lines([
            "*1 passed*",
        ])

    def test_dist_ini_specified(self, testdir):
        p1 = testdir.makepyfile(
            """
                import py
                def test_fail0():
                    assert 0
                def test_fail1():
                    raise ValueError()
                def test_ok():
                    pass
                def test_skip():
                    py.test.skip("hello")
            """, )
        testdir.makeini("""
            [pytest]
            addopts = --tx=3*popen
        """)
        result = testdir.runpytest(p1, '-d', "-v")
        result.stdout.fnmatch_lines([
            "*2*Python*",
            "*2 failed, 1 passed, 1 skipped*",
        ])
        assert result.ret == 1

    @py.test.mark.xfail("sys.platform.startswith('java')", run=False)
    def test_dist_tests_with_crash(self, testdir):
        if not hasattr(py.std.os, 'kill'):
            py.test.skip("no os.kill")

        p1 = testdir.makepyfile("""
                import py
                def test_fail0():
                    assert 0
                def test_fail1():
                    raise ValueError()
                def test_ok():
                    pass
                def test_skip():
                    py.test.skip("hello")
                def test_crash():
                    import time
                    import os
                    time.sleep(0.5)
                    os.kill(os.getpid(), 15)
            """)
        result = testdir.runpytest(p1, "-v", '-d', '-n1')
        result.stdout.fnmatch_lines([
            "*Python*", "*PASS**test_ok*", "*node*down*",
            "*3 failed, 1 passed, 1 skipped*"
        ])
        assert result.ret == 1

    def test_distribution_rsyncdirs_example(self, testdir):
        source = testdir.mkdir("source")
        dest = testdir.mkdir("dest")
        subdir = source.mkdir("example_pkg")
        subdir.ensure("__init__.py")
        p = subdir.join("test_one.py")
        p.write("def test_5():\n  assert not __file__.startswith(%r)" % str(p))
        result = testdir.runpytest("-v", "-d",
                                   "--rsyncdir=%(subdir)s" % locals(),
                                   "--tx=popen//chdir=%(dest)s" % locals(), p)
        assert result.ret == 0
        result.stdout.fnmatch_lines([
            "*0* *cwd*",
            # "RSyncStart: [G1]",
            # "RSyncFinished: [G1]",
            "*1 passed*"
        ])
        assert dest.join(subdir.basename).check(dir=1)

    def test_data_exchange(self, testdir):
        testdir.makeconftest("""
            # This hook only called on master.
            def pytest_configure_node(node):
                node.slaveinput['a'] = 42
                node.slaveinput['b'] = 7

            def pytest_configure(config):
                # this attribute is only set on slaves
                if hasattr(config, 'slaveinput'):
                    a = config.slaveinput['a']
                    b = config.slaveinput['b']
                    r = a + b
                    config.slaveoutput['r'] = r

            # This hook only called on master.
            def pytest_testnodedown(node, error):
                node.config.calc_result = node.slaveoutput['r']

            def pytest_terminal_summary(terminalreporter):
                if not hasattr(terminalreporter.config, 'slaveinput'):
                    calc_result = terminalreporter.config.calc_result
                    terminalreporter._tw.sep('-',
                        'calculated result is %s' % calc_result)
        """)
        p1 = testdir.makepyfile("def test_func(): pass")
        result = testdir.runpytest("-v", p1, '-d', '--tx=popen')
        result.stdout.fnmatch_lines(
            ["*0*Python*", "*calculated result is 49*", "*1 passed*"])
        assert result.ret == 0

    def test_keyboardinterrupt_hooks_issue79(self, testdir):
        testdir.makepyfile(
            __init__="",
            test_one="""
            def test_hello():
                raise KeyboardInterrupt()
        """)
        testdir.makeconftest("""
            def pytest_sessionfinish(session):
                # on the slave
                if hasattr(session.config, 'slaveoutput'):
                    session.config.slaveoutput['s2'] = 42
            # on the master
            def pytest_testnodedown(node, error):
                assert node.slaveoutput['s2'] == 42
                print ("s2call-finished")
        """)
        args = ["-n1", "--debug"]
        result = testdir.runpytest_subprocess(*args)
        s = result.stdout.str()
        assert result.ret == 2
        assert 's2call' in s
        assert "Interrupted" in s

    def test_keyboard_interrupt_dist(self, testdir):
        # xxx could be refined to check for return code
        testdir.makepyfile("""
            def test_sleep():
                import time
                time.sleep(10)
        """)
        child = testdir.spawn_pytest("-n1 -v")
        child.expect(".*test_sleep.*")
        child.kill(2)  # keyboard interrupt
        child.expect(".*KeyboardInterrupt.*")
        # child.expect(".*seconds.*")
        child.close()
        # assert ret == 2


class TestDistEach:
    def test_simple(self, testdir):
        testdir.makepyfile("""
            def test_hello():
                pass
        """)
        result = testdir.runpytest_subprocess("--debug", "--dist=each",
                                              "--tx=2*popen")
        assert not result.ret
        result.stdout.fnmatch_lines(["*2 pass*"])

    @py.test.mark.xfail(
        run=False,
        reason="other python versions might not have py.test installed")
    def test_simple_diffoutput(self, testdir):
        interpreters = []
        for name in ("python2.5", "python2.6"):
            interp = py.path.local.sysfind(name)
            if interp is None:
                py.test.skip("%s not found" % name)
            interpreters.append(interp)

        testdir.makepyfile(
            __init__="",
            test_one="""
            import sys
            def test_hello():
                print("%s...%s" % sys.version_info[:2])
                assert 0
        """)
        args = ["--dist=each", "-v"]
        args += ["--tx", "popen//python=%s" % interpreters[0]]
        args += ["--tx", "popen//python=%s" % interpreters[1]]
        result = testdir.runpytest(*args)
        s = result.stdout.str()
        assert "2...5" in s
        assert "2...6" in s


class TestTerminalReporting:
    def test_pass_skip_fail(self, testdir):
        testdir.makepyfile("""
            import py
            def test_ok():
                pass
            def test_skip():
                py.test.skip("xx")
            def test_func():
                assert 0
        """)
        result = testdir.runpytest("-n1", "-v")
        result.stdout.fnmatch_lines_random([
            "*PASS*test_pass_skip_fail.py*test_ok*",
            "*SKIP*test_pass_skip_fail.py*test_skip*",
            "*FAIL*test_pass_skip_fail.py*test_func*",
        ])
        result.stdout.fnmatch_lines([
            "*def test_func():",
            ">       assert 0",
            "E       assert 0",
        ])

    def test_fail_platinfo(self, testdir):
        testdir.makepyfile("""
            def test_func():
                assert 0
        """)
        result = testdir.runpytest("-n1", "-v")
        result.stdout.fnmatch_lines([
            "*FAIL*test_fail_platinfo.py*test_func*",
            "*0*Python*",
            "*def test_func():",
            ">       assert 0",
            "E       assert 0",
        ])


def test_teardownfails_one_function(testdir):
    p = testdir.makepyfile("""
        def test_func():
            pass
        def teardown_function(function):
            assert 0
    """)
    result = testdir.runpytest(p, '-n1', '--tx=popen')
    result.stdout.fnmatch_lines(
        ["*def teardown_function(function):*", "*1 passed*1 error*"])


@py.test.mark.xfail
def test_terminate_on_hangingnode(testdir):
    p = testdir.makeconftest("""
        def pytest_sessionfinish(session):
            if session.nodeid == "my": # running on slave
                import time
                time.sleep(3)
    """)
    result = testdir.runpytest(p, '--dist=each', '--tx=popen//id=my')
    assert result.duration < 2.0
    result.stdout.fnmatch_lines([
        "*killed*my*",
    ])


@pytest.mark.xfail(reason="works if run outside test suite", run=False)
def test_session_hooks(testdir):
    testdir.makeconftest("""
        import sys
        def pytest_sessionstart(session):
            sys.pytestsessionhooks = session
        def pytest_sessionfinish(session):
            if hasattr(session.config, 'slaveinput'):
                name = "slave"
            else:
                name = "master"
            f = open(name, "w")
            f.write("xy")
            f.close()
            # let's fail on the slave
            if name == "slave":
                raise ValueError(42)
    """)
    p = testdir.makepyfile("""
        import sys
        def test_hello():
            assert hasattr(sys, 'pytestsessionhooks')
    """)
    result = testdir.runpytest(p, "--dist=each", "--tx=popen")
    result.stdout.fnmatch_lines([
        "*ValueError*",
        "*1 passed*",
    ])
    assert not result.ret
    d = result.parseoutcomes()
    assert d['passed'] == 1
    assert testdir.tmpdir.join("slave").check()
    assert testdir.tmpdir.join("master").check()


def test_session_testscollected(testdir):
    """
    Make sure master node is updating the session object with the number
    of tests collected from the slaves.
    """
    testdir.makepyfile(test_foo="""
        import pytest
        @pytest.mark.parametrize('i', range(3))
        def test_ok(i):
            pass
    """)
    testdir.makeconftest("""
        def pytest_sessionfinish(session):
            collected = getattr(session, 'testscollected', None)
            with open('testscollected', 'w') as f:
                f.write('collected = %s' % collected)
    """)
    result = testdir.inline_run("-n1")
    result.assertoutcome(passed=3)
    collected_file = testdir.tmpdir.join('testscollected')
    assert collected_file.isfile()
    assert collected_file.read() == 'collected = 3'


def test_funcarg_teardown_failure(testdir):
    p = testdir.makepyfile("""
        import pytest
        @pytest.fixture
        def myarg(request):
            def teardown(val):
                raise ValueError(val)
            return request.cached_setup(setup=lambda: 42, teardown=teardown,
                scope="module")
        def test_hello(myarg):
            pass
    """)
    result = testdir.runpytest_subprocess("--debug", p)  # , "-n1")
    result.stdout.fnmatch_lines([
        "*ValueError*42*",
        "*1 passed*1 error*",
    ])
    assert result.ret


def test_crashing_item(testdir):
    p = testdir.makepyfile("""
        import py
        import os
        def test_crash():
            py.process.kill(os.getpid())
        def test_noncrash():
            pass
    """)
    result = testdir.runpytest("-n2", p)
    result.stdout.fnmatch_lines([
        "*crashed*test_crash*", "*1 failed*1 passed*"
    ])


def test_skipping(testdir):
    p = testdir.makepyfile("""
        import pytest
        def test_crash():
            pytest.skip("hello")
    """)
    result = testdir.runpytest("-n1", '-rs', p)
    assert result.ret == 0
    result.stdout.fnmatch_lines(["*hello*", "*1 skipped*"])


def test_issue34_pluginloading_in_subprocess(testdir):
    testdir.tmpdir.join("plugin123.py").write(
        py.code.Source("""
        def pytest_namespace():
            return {'sample_variable': 'testing'}
    """))
    testdir.makepyfile("""
        import pytest
        def test_hello():
            assert pytest.sample_variable == "testing"
    """)
    result = testdir.runpytest_subprocess("-n1", "-p", "plugin123")
    assert result.ret == 0
    result.stdout.fnmatch_lines([
        "*1 passed*",
    ])


def test_fixture_scope_caching_issue503(testdir):
    p1 = testdir.makepyfile("""
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
    """)
    result = testdir.runpytest(p1, '-v', '-n1')
    assert result.ret == 0
    result.stdout.fnmatch_lines([
        "*2 passed*",
    ])


def test_issue_594_random_parametrize(testdir):
    """
    Make sure that tests that are randomly parametrized display an appropriate
    error message, instead of silently skipping the entire test run.
    """
    p1 = testdir.makepyfile("""
        import pytest
        import random

        xs = list(range(10))
        random.shuffle(xs)
        @pytest.mark.parametrize('x', xs)
        def test_foo(x):
            assert 1
    """)
    result = testdir.runpytest(p1, '-v', '-n4')
    assert result.ret == 1
    result.stdout.fnmatch_lines([
        "Different tests were collected between gw* and gw*",
    ])


def test_tmpdir_disabled(testdir):
    """Test xdist doesn't break if internal tmpdir plugin is disabled (#22).
    """
    p1 = testdir.makepyfile("""
        def test_ok():
            pass
    """)
    result = testdir.runpytest(p1, "-n1", '-p', 'no:tmpdir')
    assert result.ret == 0
    result.stdout.fnmatch_lines("*1 passed*")


@pytest.mark.parametrize('plugin', ['xdist.looponfail', 'xdist.boxed'])
def test_sub_plugins_disabled(testdir, plugin):
    """Test that xdist doesn't break if we disable any of its sub-plugins. (#32)
    """
    p1 = testdir.makepyfile("""
        def test_ok():
            pass
    """)
    result = testdir.runpytest(p1, "-n1", '-p', 'no:%s' % plugin)
    assert result.ret == 0
    result.stdout.fnmatch_lines("*1 passed*")


class TestNodeFailure:
    def test_load_single(self, testdir):
        f = testdir.makepyfile("""
            import os
            def test_a(): os._exit(1)
            def test_b(): pass
        """)
        res = testdir.runpytest(f, '-n1')
        res.stdout.fnmatch_lines([
            "*Replacing crashed slave*",
            "*Slave*crashed while running*",
            "*1 failed*1 passed*",
        ])

    def test_load_multiple(self, testdir):
        f = testdir.makepyfile("""
            import os
            def test_a(): pass
            def test_b(): os._exit(1)
            def test_c(): pass
            def test_d(): pass
        """)
        res = testdir.runpytest(f, '-n2')
        res.stdout.fnmatch_lines([
            "*Replacing crashed slave*",
            "*Slave*crashed while running*",
            "*1 failed*3 passed*",
        ])

    def test_each_single(self, testdir):
        f = testdir.makepyfile("""
            import os
            def test_a(): os._exit(1)
            def test_b(): pass
        """)
        res = testdir.runpytest(f, '--dist=each', '--tx=popen')
        res.stdout.fnmatch_lines([
            "*Replacing crashed slave*",
            "*Slave*crashed while running*",
            "*1 failed*1 passed*",
        ])

    @pytest.mark.xfail(reason='#20: xdist race condition on node restart')
    def test_each_multiple(self, testdir):
        f = testdir.makepyfile("""
            import os
            def test_a(): os._exit(1)
            def test_b(): pass
        """)
        res = testdir.runpytest(f, '--dist=each', '--tx=2*popen')
        res.stdout.fnmatch_lines([
            "*Replacing crashed slave*",
            "*Slave*crashed while running*",
            "*2 failed*2 passed*",
        ])

    def test_max_slave_restart(self, testdir):
        f = testdir.makepyfile("""
            import os
            def test_a(): pass
            def test_b(): os._exit(1)
            def test_c(): os._exit(1)
            def test_d(): pass
        """)
        res = testdir.runpytest(f, '-n4', '--max-slave-restart=1')
        res.stdout.fnmatch_lines([
            "*Replacing crashed slave*",
            "*Maximum crashed slaves reached: 1*",
            "*Slave*crashed while running*",
            "*Slave*crashed while running*",
            "*2 failed*2 passed*",
        ])

    def test_disable_restart(self, testdir):
        f = testdir.makepyfile("""
            import os
            def test_a(): pass
            def test_b(): os._exit(1)
            def test_c(): pass
        """)
        res = testdir.runpytest(f, '-n4', '--max-slave-restart=0')
        res.stdout.fnmatch_lines([
            "*Slave restarting disabled*",
            "*Slave*crashed while running*",
            "*1 failed*2 passed*",
        ])


@pytest.mark.parametrize('n', [0, 2])
def test_worker_id_fixture(testdir, n):
    import glob
    f = testdir.makepyfile("""
        import pytest
        @pytest.mark.parametrize("run_num", range(2))
        def test_worker_id1(worker_id, run_num):
            with open("worker_id%s.txt" % run_num, "w") as f:
                f.write(worker_id)
    """)
    result = testdir.runpytest(f, "-n%d" % n)
    result.stdout.fnmatch_lines('* 2 passed in *')
    worker_ids = set()
    for fname in glob.glob(str(testdir.tmpdir.join("*.txt"))):
        with open(fname) as f:
            worker_ids.add(f.read().strip())
    if n == 0:
        assert worker_ids == set(['master'])
    else:
        assert worker_ids == set(['gw0', 'gw1'])


def test_color_yes_collection_on_non_atty(testdir, request):
    """skip collect progress report when working on non-terminals.

    Similar to pytest-dev/pytest#1397
    """
    tr = request.config.pluginmanager.getplugin("terminalreporter")
    if not hasattr(tr, 'isatty'):
        pytest.skip('only valid for newer pytest versions')
    testdir.makepyfile("""
        import pytest
        @pytest.mark.parametrize('i', range(10))
        def test_this(i):
            assert 1
    """)
    args = ['--color=yes', '-n2']
    result = testdir.runpytest(*args)
    assert 'test session starts' in result.stdout.str()
    assert '\x1b[1m' in result.stdout.str()
    assert 'gw0 [10] / gw1 [10]' in result.stdout.str()
    assert 'gw0 C / gw1 C' not in result.stdout.str()


def test_internal_error_with_maxfail(testdir):
    """
    Internal error when using --maxfail option (#62, #65).
    """
    testdir.makepyfile("""
        import pytest

        @pytest.fixture(params=['1', '2'])
        def crasher():
            raise RuntimeError

        def test_aaa0(crasher):
            pass
        def test_aaa1(crasher):
            pass
    """)
    result = testdir.runpytest_subprocess('--maxfail=1', '-n1')
    result.stdout.fnmatch_lines(['* 1 error in *'])
    assert 'INTERNALERROR' not in result.stderr.str()

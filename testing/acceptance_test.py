import py

class TestDistribution:
    def test_manytests_to_one_popen(self, testdir):
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
            """, 
        )
        result = testdir.runpytest(p1, '-d', '--tx=popen', '--tx=popen')
        result.stdout.fnmatch_lines([
            "*0*popen*Python*",
            "*1*popen*Python*",
            "*2 failed, 1 passed, 1 skipped*",
        ])
        assert result.ret == 1

    def test_dist_conftest_specified(self, testdir):
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
            """, 
        )
        testdir.makeconftest("""
            option_tx = 'popen popen popen'.split()
        """)
        result = testdir.runpytest(p1, '-d')
        result.stdout.fnmatch_lines([
            "*0*popen*Python*",
            "*1*popen*Python*",
            "*2*popen*Python*",
            "*2 failed, 1 passed, 1 skipped*",
        ])
        assert result.ret == 1

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
            """
        )
        result = testdir.runpytest(p1, '-d', '--tx=3*popen')
        result.stdout.fnmatch_lines([
            "*popen*Python*",
            "*popen*Python*",
            "*popen*Python*",
            "*node down*",
            "*3 failed, 1 passed, 1 skipped*"
        ])
        assert result.ret == 1

    def test_distribution_rsyncdirs_example(self, testdir):
        source = testdir.mkdir("source")
        dest = testdir.mkdir("dest")
        subdir = source.mkdir("example_pkg")
        subdir.ensure("__init__.py")
        p = subdir.join("test_one.py")
        p.write("def test_5(): assert not __file__.startswith(%r)" % str(p))
        result = testdir.runpytest("-d", "--rsyncdir=%(subdir)s" % locals(), 
            "--tx=popen//chdir=%(dest)s" % locals(), p)
        assert result.ret == 0
        result.stdout.fnmatch_lines([
            "*0* *popen*platform*",
            #"RSyncStart: [G1]",
            #"RSyncFinished: [G1]",
            "*1 passed*"
        ])
        assert dest.join(subdir.basename).check(dir=1)

    def test_dist_each(self, testdir):
        interpreters = []
        for name in ("python2.4", "python2.5"):
            interp = py.path.local.sysfind(name)
            if interp is None:
                py.test.skip("%s not found" % name)
            interpreters.append(interp)

        testdir.makepyfile(__init__="", test_one="""
            import sys
            def test_hello():
                print("%s...%s" % sys.version_info[:2])
                assert 0
        """)
        args = ["--dist=each"]
        args += ["--tx", "popen//python=%s" % interpreters[0]]
        args += ["--tx", "popen//python=%s" % interpreters[1]]
        result = testdir.runpytest(*args)
        s = result.stdout.str()
        assert "2.4" in s
        assert "2.5" in s

    def test_data_exchange(self, testdir):
        c1 = testdir.makeconftest("""
            # This hook only called on master.
            def pytest_configure_node(node):
                node.slaveinput['a'] = 42
                node.slaveinput['b'] = 7

            # This hook only takes action on slave.
            def pytest_configure(config):
                if hasattr(config, 'slaveinput'):
                    a = config.slaveinput['a']
                    b = config.slaveinput['b']
                    r = a + b
                    config.slaveoutput['r'] = r

            # This hook only called on master.
            def pytest_testnodedown(node, error):
                node.config.calc_result = node.slaveoutput['r']

            # This hook only takes action on master.
            def pytest_terminal_summary(terminalreporter):
                if not hasattr(terminalreporter.config, 'slaveinput'):
                    calc_result = terminalreporter.config.calc_result
                    terminalreporter._tw.sep('-', 
                        'calculated result is %s' % calc_result)
        """)
        p1 = testdir.makepyfile("def test_func(): pass")
        result = testdir.runpytest(p1, '-d', '--tx=popen')
        result.stdout.fnmatch_lines([
            "*popen*Python*",
            "*calculated result is 49*",
            "*1 passed*"
        ])
        assert result.ret == 0

    def test_keyboardinterrupt_hooks_issue79(self, testdir):
        testdir.makepyfile(__init__="", test_one="""
            def test_hello():
                raise KeyboardInterrupt()
        """)
        testdir.makeconftest("""
            def pytest_sessionfinish(session):
                if hasattr(session.config, 'slaveoutput'):
                    session.config.slaveoutput['s2'] = 42
            def pytest_testnodedown(node, error):
                assert node.slaveoutput['s2'] == 42
                print ("s2call-finished")
        """)
        args = ["-n1"]
        result = testdir.runpytest(*args)
        s = result.stdout.str()
        assert result.ret 
        assert 'SIGINT' in s
        assert 's2call' in s

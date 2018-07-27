import py
import execnet
from xdist.workermanage import NodeManager


def test_dist_incompatibility_messages(testdir):
    result = testdir.runpytest("--pdb", "--looponfail")
    assert result.ret != 0
    result = testdir.runpytest("--pdb", "-n", "3")
    assert result.ret != 0
    assert "incompatible" in result.stderr.str()
    result = testdir.runpytest("--pdb", "-d", "--tx", "popen")
    assert result.ret != 0
    assert "incompatible" in result.stderr.str()


def test_dist_options(testdir):
    from xdist.plugin import pytest_cmdline_main as check_options
    config = testdir.parseconfigure("-n 2")
    check_options(config)
    assert config.option.dist == "load"
    assert config.option.tx == ['popen'] * 2
    config = testdir.parseconfigure("--numprocesses", "2")
    check_options(config)
    assert config.option.dist == "load"
    assert config.option.tx == ['popen'] * 2
    config = testdir.parseconfigure("-d")
    check_options(config)
    assert config.option.dist == "load"


def test_auto_detect_cpus(testdir, monkeypatch):
    import os
    if hasattr(os, 'sched_getaffinity'):
        monkeypatch.setattr(os, 'sched_getaffinity', lambda _pid: set(range(99)))
    elif hasattr(os, 'cpu_count'):
        monkeypatch.setattr(os, 'cpu_count', lambda: 99)
    else:
        import multiprocessing
        monkeypatch.setattr(multiprocessing, 'cpu_count', lambda: 99)

    config = testdir.parseconfigure("-n2")
    assert config.getoption('numprocesses') == 2

    config = testdir.parseconfigure("-nauto")
    assert config.getoption('numprocesses') == 99

    monkeypatch.delattr(os, 'sched_getaffinity', raising=False)
    monkeypatch.setenv('TRAVIS', 'true')
    config = testdir.parseconfigure("-nauto")
    assert config.getoption('numprocesses') == 2


def test_boxed_with_collect_only(testdir):
    from xdist.plugin import pytest_cmdline_main as check_options
    config = testdir.parseconfigure("-n1", "--boxed")
    check_options(config)
    assert config.option.forked

    config = testdir.parseconfigure("-n1", "--collect-only")
    check_options(config)
    assert not config.option.forked

    config = testdir.parseconfigure("-n1", "--boxed", "--collect-only")
    check_options(config)
    assert config.option.forked


def test_dsession_with_collect_only(testdir):
    from xdist.plugin import pytest_cmdline_main as check_options
    from xdist.plugin import pytest_configure as configure

    config = testdir.parseconfigure("-n1")
    check_options(config)
    configure(config)
    assert config.pluginmanager.hasplugin("dsession")

    config = testdir.parseconfigure("-n1", "--collect-only")
    check_options(config)
    configure(config)
    assert not config.pluginmanager.hasplugin("dsession")


class TestDistOptions:
    def test_getxspecs(self, testdir):
        config = testdir.parseconfigure("--tx=popen", "--tx", "ssh=xyz")
        nodemanager = NodeManager(config)
        xspecs = nodemanager._getxspecs()
        assert len(xspecs) == 2
        print(xspecs)
        assert xspecs[0].popen
        assert xspecs[1].ssh == "xyz"

    def test_xspecs_multiplied(self, testdir):
        config = testdir.parseconfigure("--tx=3*popen", )
        xspecs = NodeManager(config)._getxspecs()
        assert len(xspecs) == 3
        assert xspecs[1].popen

    def test_getrsyncdirs(self, testdir):
        config = testdir.parseconfigure('--rsyncdir=' + str(testdir.tmpdir))
        nm = NodeManager(config, specs=[execnet.XSpec("popen")])
        assert not nm._getrsyncdirs()
        nm = NodeManager(config, specs=[execnet.XSpec("popen//chdir=qwe")])
        assert nm.roots
        assert testdir.tmpdir in nm.roots

    def test_getrsyncignore(self, testdir):
        config = testdir.parseconfigure('--rsyncignore=fo*')
        nm = NodeManager(config, specs=[execnet.XSpec("popen//chdir=qwe")])
        assert 'fo*' in nm.rsyncoptions['ignores']

    def test_getrsyncdirs_with_conftest(self, testdir):
        p = py.path.local()
        for bn in 'x y z'.split():
            p.mkdir(bn)
        testdir.makeini("""
            [pytest]
            rsyncdirs= x
        """)
        config = testdir.parseconfigure(
            testdir.tmpdir, '--rsyncdir=y', '--rsyncdir=z')
        nm = NodeManager(config, specs=[execnet.XSpec("popen//chdir=xyz")])
        roots = nm._getrsyncdirs()
        # assert len(roots) == 3 + 1 # pylib
        assert py.path.local('y') in roots
        assert py.path.local('z') in roots
        assert testdir.tmpdir.join('x') in roots

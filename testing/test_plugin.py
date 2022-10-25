from contextlib import suppress
from pathlib import Path
import sys
import os

import execnet
from xdist.workermanage import NodeManager

import pytest


@pytest.fixture
def monkeypatch_3_cpus(monkeypatch: pytest.MonkeyPatch):
    """Make pytest-xdist believe the system has 3 CPUs"""
    # block import
    monkeypatch.setitem(sys.modules, "psutil", None)  # type: ignore
    monkeypatch.delattr(os, "sched_getaffinity", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 3)


def test_dist_incompatibility_messages(pytester: pytest.Pytester) -> None:
    result = pytester.runpytest("--pdb", "--looponfail")
    assert result.ret != 0
    result = pytester.runpytest("--pdb", "-n", "3")
    assert result.ret != 0
    assert "incompatible" in result.stderr.str()
    result = pytester.runpytest("--pdb", "-d", "--tx", "popen")
    assert result.ret != 0
    assert "incompatible" in result.stderr.str()


def test_dist_options(pytester: pytest.Pytester) -> None:
    from xdist.plugin import pytest_cmdline_main as check_options

    config = pytester.parseconfigure("-n 2")
    check_options(config)
    assert config.option.dist == "load"
    assert config.option.tx == ["popen"] * 2
    config = pytester.parseconfigure("--numprocesses", "2")
    check_options(config)
    assert config.option.dist == "load"
    assert config.option.tx == ["popen"] * 2
    config = pytester.parseconfigure("--numprocesses", "3", "--maxprocesses", "2")
    check_options(config)
    assert config.option.dist == "load"
    assert config.option.tx == ["popen"] * 2
    config = pytester.parseconfigure("-d")
    check_options(config)
    assert config.option.dist == "load"


def test_auto_detect_cpus(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    from xdist.plugin import pytest_cmdline_main as check_options

    with suppress(ImportError):
        import psutil

        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: None)

    if hasattr(os, "sched_getaffinity"):
        monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: set(range(99)))
    elif hasattr(os, "cpu_count"):
        monkeypatch.setattr(os, "cpu_count", lambda: 99)
    else:
        import multiprocessing

        monkeypatch.setattr(multiprocessing, "cpu_count", lambda: 99)

    config = pytester.parseconfigure("-n2")
    assert config.getoption("numprocesses") == 2

    config = pytester.parseconfigure("-nauto")
    check_options(config)
    assert config.getoption("numprocesses") == 99

    config = pytester.parseconfigure("-nauto", "--pdb")
    check_options(config)
    assert config.getoption("usepdb")
    assert config.getoption("numprocesses") == 0
    assert config.getoption("dist") == "no"

    config = pytester.parseconfigure("-nlogical", "--pdb")
    check_options(config)
    assert config.getoption("usepdb")
    assert config.getoption("numprocesses") == 0
    assert config.getoption("dist") == "no"

    monkeypatch.delattr(os, "sched_getaffinity", raising=False)
    monkeypatch.setenv("TRAVIS", "true")
    config = pytester.parseconfigure("-nauto")
    check_options(config)
    assert config.getoption("numprocesses") == 2


def test_auto_detect_cpus_psutil(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    from xdist.plugin import pytest_cmdline_main as check_options

    psutil = pytest.importorskip("psutil")

    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 84 if logical else 42)

    config = pytester.parseconfigure("-nauto")
    check_options(config)
    assert config.getoption("numprocesses") == 42

    config = pytester.parseconfigure("-nlogical")
    check_options(config)
    assert config.getoption("numprocesses") == 84


def test_auto_detect_cpus_os(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, monkeypatch_3_cpus
) -> None:
    from xdist.plugin import pytest_cmdline_main as check_options

    config = pytester.parseconfigure("-nauto")
    check_options(config)
    assert config.getoption("numprocesses") == 3

    config = pytester.parseconfigure("-nlogical")
    check_options(config)
    assert config.getoption("numprocesses") == 3


def test_hook_auto_num_workers(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    from xdist.plugin import pytest_cmdline_main as check_options

    pytester.makeconftest(
        """
        def pytest_xdist_auto_num_workers():
            return 42
    """
    )
    config = pytester.parseconfigure("-nauto")
    check_options(config)
    assert config.getoption("numprocesses") == 42

    config = pytester.parseconfigure("-nlogical")
    check_options(config)
    assert config.getoption("numprocesses") == 42


def test_hook_auto_num_workers_arg(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    # config.option.numprocesses is a pytest feature,
    # but we document it so let's test it.
    from xdist.plugin import pytest_cmdline_main as check_options

    pytester.makeconftest(
        """
        def pytest_xdist_auto_num_workers(config):
            if config.option.numprocesses == 'auto':
                return 42
            if config.option.numprocesses == 'logical':
                return 8
    """
    )
    config = pytester.parseconfigure("-nauto")
    check_options(config)
    assert config.getoption("numprocesses") == 42

    config = pytester.parseconfigure("-nlogical")
    check_options(config)
    assert config.getoption("numprocesses") == 8


def test_hook_auto_num_workers_none(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, monkeypatch_3_cpus
) -> None:
    # Returning None from a hook to skip it is pytest behavior,
    # but we document it so let's test it.
    from xdist.plugin import pytest_cmdline_main as check_options

    pytester.makeconftest(
        """
        def pytest_xdist_auto_num_workers():
            return None
    """
    )
    config = pytester.parseconfigure("-nauto")
    check_options(config)
    assert config.getoption("numprocesses") == 3

    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "5")

    config = pytester.parseconfigure("-nauto")
    check_options(config)
    assert config.getoption("numprocesses") == 5


def test_envvar_auto_num_workers(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    from xdist.plugin import pytest_cmdline_main as check_options

    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "7")

    config = pytester.parseconfigure("-nauto")
    check_options(config)
    assert config.getoption("numprocesses") == 7

    config = pytester.parseconfigure("-nlogical")
    check_options(config)
    assert config.getoption("numprocesses") == 7


def test_envvar_auto_num_workers_warn(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, monkeypatch_3_cpus
) -> None:
    from xdist.plugin import pytest_cmdline_main as check_options

    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "fourscore")

    config = pytester.parseconfigure("-nauto")
    with pytest.warns(UserWarning):
        check_options(config)
    assert config.getoption("numprocesses") == 3


def test_auto_num_workers_hook_overrides_envvar(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, monkeypatch_3_cpus
) -> None:
    from xdist.plugin import pytest_cmdline_main as check_options

    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "987")
    pytester.makeconftest(
        """
        def pytest_xdist_auto_num_workers():
            return 2
    """
    )
    config = pytester.parseconfigure("-nauto")
    check_options(config)
    assert config.getoption("numprocesses") == 2

    config = pytester.parseconfigure("-nauto")
    check_options(config)
    assert config.getoption("numprocesses") == 2


def test_dsession_with_collect_only(pytester: pytest.Pytester) -> None:
    from xdist.plugin import pytest_cmdline_main as check_options
    from xdist.plugin import pytest_configure as configure

    config = pytester.parseconfigure("-n1")
    check_options(config)
    configure(config)
    assert config.pluginmanager.hasplugin("dsession")

    config = pytester.parseconfigure("-n1", "--collect-only")
    check_options(config)
    configure(config)
    assert not config.pluginmanager.hasplugin("dsession")


def test_testrunuid_provided(pytester: pytest.Pytester) -> None:
    config = pytester.parseconfigure("--testrunuid", "test123", "--tx=popen")
    nm = NodeManager(config)
    assert nm.testrunuid == "test123"


def test_testrunuid_generated(pytester: pytest.Pytester) -> None:
    config = pytester.parseconfigure("--tx=popen")
    nm = NodeManager(config)
    assert len(nm.testrunuid) == 32


class TestDistOptions:
    def test_getxspecs(self, pytester: pytest.Pytester) -> None:
        config = pytester.parseconfigure("--tx=popen", "--tx", "ssh=xyz")
        nodemanager = NodeManager(config)
        xspecs = nodemanager._getxspecs()
        assert len(xspecs) == 2
        print(xspecs)
        assert xspecs[0].popen
        assert xspecs[1].ssh == "xyz"

    def test_xspecs_multiplied(self, pytester: pytest.Pytester) -> None:
        config = pytester.parseconfigure("--tx=3*popen")
        xspecs = NodeManager(config)._getxspecs()
        assert len(xspecs) == 3
        assert xspecs[1].popen

    def test_getrsyncdirs(self, pytester: pytest.Pytester) -> None:
        config = pytester.parseconfigure("--rsyncdir=" + str(pytester.path))
        nm = NodeManager(config, specs=[execnet.XSpec("popen")])
        assert not nm._getrsyncdirs()
        nm = NodeManager(config, specs=[execnet.XSpec("popen//chdir=qwe")])
        assert nm.roots
        assert pytester.path in nm.roots

    def test_getrsyncignore(self, pytester: pytest.Pytester) -> None:
        config = pytester.parseconfigure("--rsyncignore=fo*")
        nm = NodeManager(config, specs=[execnet.XSpec("popen//chdir=qwe")])
        assert "fo*" in nm.rsyncoptions["ignores"]

    def test_getrsyncdirs_with_conftest(self, pytester: pytest.Pytester) -> None:
        p = Path.cwd()
        for bn in ("x", "y", "z"):
            p.joinpath(bn).mkdir()
        pytester.makeini(
            """
            [pytest]
            rsyncdirs= x
        """
        )
        config = pytester.parseconfigure(pytester.path, "--rsyncdir=y", "--rsyncdir=z")
        nm = NodeManager(config, specs=[execnet.XSpec("popen//chdir=xyz")])
        roots = nm._getrsyncdirs()
        # assert len(roots) == 3 + 1 # pylib
        assert Path("y").resolve() in roots
        assert Path("z").resolve() in roots
        assert pytester.path.joinpath("x") in roots

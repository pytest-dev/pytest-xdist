import os
import uuid
import sys
from pathlib import Path

import py
import pytest
from _pytest.stash import StashKey

PYTEST_GTE_7 = hasattr(pytest, "version_tuple") and pytest.version_tuple >= (7, 0)  # type: ignore[attr-defined]

_sys_path = list(sys.path)  # freeze a copy of sys.path at interpreter startup

shared_key = StashKey["str"]()


@pytest.hookimpl
def pytest_xdist_auto_num_workers(config):
    try:
        import psutil
    except ImportError:
        pass
    else:
        use_logical = config.option.numprocesses == "logical"
        count = psutil.cpu_count(logical=use_logical) or psutil.cpu_count()
        if count:
            return count
    try:
        from os import sched_getaffinity

        def cpu_count():
            return len(sched_getaffinity(0))

    except ImportError:
        if os.environ.get("TRAVIS") == "true":
            # workaround https://bitbucket.org/pypy/pypy/issues/2375
            return 2
        try:
            from os import cpu_count
        except ImportError:
            from multiprocessing import cpu_count
    try:
        n = cpu_count()
    except NotImplementedError:
        return 1
    return n if n else 1


def parse_numprocesses(s):
    if s in ("auto", "logical"):
        return s
    elif s is not None:
        return int(s)


@pytest.hookimpl
def pytest_addoption(parser):
    group = parser.getgroup("xdist", "distributed and subprocess testing")
    group._addoption(
        "-n",
        "--numprocesses",
        dest="numprocesses",
        metavar="numprocesses",
        action="store",
        type=parse_numprocesses,
        help="Shortcut for '--dist=load --tx=NUM*popen'. With 'auto', attempt "
        "to detect physical CPU count. With 'logical', detect logical CPU "
        "count. If physical CPU count cannot be found, falls back to logical "
        "count. This will be 0 when used with --pdb.",
    )
    group.addoption(
        "--maxprocesses",
        dest="maxprocesses",
        metavar="maxprocesses",
        action="store",
        type=int,
        help="limit the maximum number of workers to process the tests when using --numprocesses=auto",
    )
    group.addoption(
        "--max-worker-restart",
        action="store",
        default=None,
        dest="maxworkerrestart",
        help="maximum number of workers that can be restarted "
        "when crashed (set to zero to disable this feature)",
    )
    group.addoption(
        "--dist",
        metavar="distmode",
        action="store",
        choices=["each", "load", "loadscope", "loadfile", "loadgroup", "no"],
        dest="dist",
        default="no",
        help=(
            "set mode for distributing tests to exec environments.\n\n"
            "each: send each test to all available environments.\n\n"
            "load: load balance by sending any pending test to any"
            " available environment.\n\n"
            "loadscope: load balance by sending pending groups of tests in"
            " the same scope to any available environment.\n\n"
            "loadfile: load balance by sending test grouped by file"
            " to any available environment.\n\n"
            "loadgroup: like load, but sends tests marked with 'xdist_group' to the same worker.\n\n"
            "(default) no: run tests inprocess, don't distribute."
        ),
    )
    group.addoption(
        "--tx",
        dest="tx",
        action="append",
        default=[],
        metavar="xspec",
        help=(
            "add a test execution environment. some examples: "
            "--tx popen//python=python2.5 --tx socket=192.168.1.102:8888 "
            "--tx ssh=user@codespeak.net//chdir=testcache"
        ),
    )
    group._addoption(
        "-d",
        action="store_true",
        dest="distload",
        default=False,
        help="load-balance tests.  shortcut for '--dist=load'",
    )
    group.addoption(
        "--rsyncdir",
        action="append",
        default=[],
        metavar="DIR",
        help="add directory for rsyncing to remote tx nodes.",
    )
    group.addoption(
        "--rsyncignore",
        action="append",
        default=[],
        metavar="GLOB",
        help="add expression for ignores when rsyncing to remote tx nodes.",
    )
    group.addoption(
        "--boxed",
        action="store_true",
        help="backward compatibility alias for pytest-forked --forked",
    )
    group.addoption(
        "--testrunuid",
        action="store",
        help=(
            "provide an identifier shared amongst all workers as the value of "
            "the 'testrun_uid' fixture,\n\n,"
            "if not provided, 'testrun_uid' is filled with a new unique string "
            "on every test run."
        ),
    )

    parser.addini(
        "rsyncdirs",
        "list of (relative) paths to be rsynced for remote distributed testing.",
        type="paths" if PYTEST_GTE_7 else "pathlist",
    )
    parser.addini(
        "rsyncignore",
        "list of (relative) glob-style paths to be ignored for rsyncing.",
        type="paths" if PYTEST_GTE_7 else "pathlist",
    )
    parser.addini(
        "looponfailroots",
        type="paths" if PYTEST_GTE_7 else "pathlist",
        help="directories to check for changes",
        default=[Path.cwd() if PYTEST_GTE_7 else py.path.local()],
    )


# -------------------------------------------------------------------------
# distributed testing hooks
# -------------------------------------------------------------------------


@pytest.hookimpl
def pytest_addhooks(pluginmanager):
    from xdist import newhooks

    pluginmanager.add_hookspecs(newhooks)


# -------------------------------------------------------------------------
# distributed testing initialization
# -------------------------------------------------------------------------


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    if config.getoption("dist") != "no" and not config.getvalue("collectonly"):
        from xdist.dsession import DSession

        session = DSession(config)
        config.pluginmanager.register(session, "dsession")
        tr = config.pluginmanager.getplugin("terminalreporter")
        if tr:
            tr.showfspath = False
    if config.getoption("boxed"):
        warning = DeprecationWarning(
            "The --boxed command line argument is deprecated. "
            "Install pytest-forked and use --forked instead. "
            "pytest-xdist 3.0.0 will remove the --boxed argument and pytest-forked dependency."
        )
        config.issue_config_time_warning(warning, 2)
        config.option.forked = True

    config_line = (
        "xdist_group: specify group for tests should run in same session."
        "in relation to one another. " + "Provided by pytest-xdist."
    )
    config.addinivalue_line("markers", config_line)


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config):
    usepdb = config.getoption("usepdb", False)  # a core option
    if config.option.numprocesses in ("auto", "logical"):
        if usepdb:
            config.option.numprocesses = 0
            config.option.dist = "no"
        else:
            auto_num_cpus = config.hook.pytest_xdist_auto_num_workers(config=config)
            config.option.numprocesses = auto_num_cpus

    if config.option.numprocesses:
        if config.option.dist == "no":
            config.option.dist = "load"
        numprocesses = config.option.numprocesses
        if config.option.maxprocesses:
            numprocesses = min(numprocesses, config.option.maxprocesses)
        config.option.tx = ["popen"] * numprocesses
    if config.option.distload:
        config.option.dist = "load"
    val = config.getvalue
    if not val("collectonly") and val("dist") != "no" and usepdb:
        raise pytest.UsageError(
            "--pdb is incompatible with distributing tests; try using -n0 or -nauto."
        )  # noqa: E501


# -------------------------------------------------------------------------
# fixtures and API to easily know the role of current node
# -------------------------------------------------------------------------


def is_xdist_worker(request_or_session) -> bool:
    """Return `True` if this is an xdist worker, `False` otherwise

    :param request_or_session: the `pytest` `request` or `session` object
    """
    return hasattr(request_or_session.config, "workerinput")


def is_xdist_controller(request_or_session) -> bool:
    """Return `True` if this is the xdist controller, `False` otherwise

    Note: this method also returns `False` when distribution has not been
    activated at all.

    :param request_or_session: the `pytest` `request` or `session` object
    """
    return (
        not is_xdist_worker(request_or_session)
        and request_or_session.config.option.dist != "no"
    )


# ALIAS: TODO, deprecate (#592)
is_xdist_master = is_xdist_controller


def get_xdist_worker_id(request_or_session):
    """Return the id of the current worker ('gw0', 'gw1', etc) or 'master'
    if running on the controller node.

    If not distributing tests (for example passing `-n0` or not passing `-n` at all)
    also return 'master'.

    :param request_or_session: the `pytest` `request` or `session` object
    """
    if hasattr(request_or_session.config, "workerinput"):
        return request_or_session.config.workerinput["workerid"]
    else:
        # TODO: remove "master", ideally for a None
        return "master"


@pytest.fixture(scope="session")
def worker_id(request):
    """Return the id of the current worker ('gw0', 'gw1', etc) or 'master'
    if running on the master node.
    """
    # TODO: remove "master", ideally for a None
    return get_xdist_worker_id(request)


@pytest.fixture(scope="session")
def testrun_uid(request):
    """Return the unique id of the current test."""
    if hasattr(request.config, "workerinput"):
        return request.config.workerinput["testrunuid"]
    else:
        return uuid.uuid4().hex


def get_shared_data(request_or_session):
    """Return shared data and True, if it is ran from xdist_controller"""
    if is_xdist_controller(request_or_session):
        return request_or_session.config.stash.setdefault(shared_key, {}), True
    return request_or_session.config.stash.setdefault(shared_key, {}), False


@pytest.fixture(scope="session")
def add_shared_data(request, worker_id):
    """Adds data that will be collected from all workers and be accessible from master node in sessionfinish hook"""

    def _add(key, value):
        shared = request.config.stash.setdefault(shared_key, {})
        if worker_id == "master":
            # Worker shared_data are grouped together, master data aren't
            shared[key] = [value]
        else:
            shared[key] = value

    return _add

import os
import uuid

import py
import pytest


def pytest_xdist_auto_num_workers():
    try:
        import psutil
    except ImportError:
        pass
    else:
        count = psutil.cpu_count(logical=False) or psutil.cpu_count()
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
    if s == "auto":
        return "auto"
    elif s is not None:
        return int(s)


def pytest_addoption(parser):
    group = parser.getgroup("xdist", "distributed and subprocess testing")
    group._addoption(
        "-n",
        "--numprocesses",
        dest="numprocesses",
        metavar="numprocesses",
        action="store",
        type=parse_numprocesses,
        help="shortcut for '--dist=load --tx=NUM*popen', "
        "you can use 'auto' here for auto detection CPUs number on "
        "host system and it will be 0 when used with --pdb",
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
        choices=["each", "load", "loadscope", "loadfile", "no"],
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
        type="pathlist",
    )
    parser.addini(
        "rsyncignore",
        "list of (relative) glob-style paths to be ignored for rsyncing.",
        type="pathlist",
    )
    parser.addini(
        "looponfailroots",
        type="pathlist",
        help="directories to check for changes",
        default=[py.path.local()],
    )


# -------------------------------------------------------------------------
# distributed testing hooks
# -------------------------------------------------------------------------


def pytest_addhooks(pluginmanager):
    from xdist import newhooks

    pluginmanager.add_hookspecs(newhooks)


# -------------------------------------------------------------------------
# distributed testing initialization
# -------------------------------------------------------------------------


@pytest.mark.trylast
def pytest_configure(config):
    if config.getoption("dist") != "no" and not config.getvalue("collectonly"):
        from xdist.dsession import DSession

        session = DSession(config)
        config.pluginmanager.register(session, "dsession")
        tr = config.pluginmanager.getplugin("terminalreporter")
        if tr:
            tr.showfspath = False
    if config.getoption("boxed"):
        config.option.forked = True


@pytest.mark.tryfirst
def pytest_cmdline_main(config):
    usepdb = config.getoption("usepdb", False)  # a core option
    if config.option.numprocesses == "auto":
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


def is_xdist_master(request_or_session) -> bool:
    """Return `True` if this is the xdist master, `False` otherwise

    Note: this method also returns `False` when distribution has not been
    activated at all.

    :param request_or_session: the `pytest` `request` or `session` object
    """
    return (
        not is_xdist_worker(request_or_session)
        and request_or_session.config.option.dist != "no"
    )


def get_xdist_worker_id(request_or_session) -> str:
    """Return the id of the current worker ('gw0', 'gw1', etc) or 'master'
    if running on the 'master' node.

    If not distributing tests (for example passing `-n0` or not passing `-n` at all)
    also return 'master'.

    :param request_or_session: the `pytest` `request` or `session` object
    """
    if hasattr(request_or_session.config, "workerinput"):
        return request_or_session.config.workerinput["workerid"]
    else:
        return "master"


@pytest.fixture(scope="session")
def worker_id(request):
    """Return the id of the current worker ('gw0', 'gw1', etc) or 'master'
    if running on the master node.
    """
    return get_xdist_worker_id(request)


@pytest.fixture(scope="session")
def testrun_uid(request):
    """Return the unique id of the current test."""
    if hasattr(request.config, "workerinput"):
        return request.config.workerinput["testrunuid"]
    else:
        return uuid.uuid4().hex

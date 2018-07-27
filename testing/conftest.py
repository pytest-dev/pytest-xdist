import py
import pytest
import execnet


@pytest.fixture(scope="session", autouse=True)
def _ensure_imports():
    # we import some modules because pytest-2.8's testdir fixture
    # will unload all modules after each test and this cause
    # (unknown) problems with execnet.Group()
    execnet.Group
    execnet.makegateway


pytest_plugins = "pytester"

# rsyncdirs = ['.', '../xdist', py.path.local(execnet.__file__).dirpath()]


@pytest.fixture(autouse=True)
def _divert_atexit(request, monkeypatch):
    import atexit

    finalizers = []

    def finish():
        while finalizers:
            finalizers.pop()()

    monkeypatch.setattr(atexit, "register", finalizers.append)
    request.addfinalizer(finish)


def pytest_addoption(parser):
    parser.addoption(
        "--gx",
        action="append",
        dest="gspecs",
        help="add a global test environment, XSpec-syntax. ",
    )


@pytest.fixture
def specssh(request):
    return getspecssh(request.config)


@pytest.fixture
def testdir(testdir):
    # pytest before 2.8 did not have a runpytest_subprocess
    if not hasattr(testdir, "runpytest_subprocess"):
        testdir.runpytest_subprocess = testdir.runpytest
    return testdir


# configuration information for tests
def getgspecs(config):
    return [execnet.XSpec(spec) for spec in config.getvalueorskip("gspecs")]


def getspecssh(config):
    xspecs = getgspecs(config)
    for spec in xspecs:
        if spec.ssh:
            if not py.path.local.sysfind("ssh"):
                py.test.skip("command not found: ssh")
            return str(spec)
    py.test.skip("need '--gx ssh=...'")


def getsocketspec(config):
    xspecs = getgspecs(config)
    for spec in xspecs:
        if spec.socket:
            return spec
    py.test.skip("need '--gx socket=...'")

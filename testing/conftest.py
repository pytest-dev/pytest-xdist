import six
import py
import pytest
import execnet

pytest_plugins = "pytester"

if six.PY2:

    @pytest.fixture(scope="session", autouse=True)
    def _ensure_imports():
        # we import some modules because pytest-2.8's testdir fixture
        # will unload all modules after each test and this cause
        # (unknown) problems with execnet.Group()
        execnet.Group
        execnet.makegateway


@pytest.fixture(autouse=True)
def _divert_atexit(request, monkeypatch):
    import atexit

    finalizers = []

    def fake_register(func, *args, **kwargs):
        finalizers.append((func, args, kwargs))

    monkeypatch.setattr(atexit, "register", fake_register)

    yield

    while finalizers:
        func, args, kwargs = finalizers.pop()
        func(*args, **kwargs)


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

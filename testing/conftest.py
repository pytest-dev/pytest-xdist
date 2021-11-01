import execnet
import pytest
import shutil
from typing import List

pytest_plugins = "pytester"


@pytest.fixture(autouse=True)
def _divert_atexit(request, monkeypatch: pytest.MonkeyPatch):
    import atexit

    finalizers = []

    def fake_register(func, *args, **kwargs):
        finalizers.append((func, args, kwargs))

    monkeypatch.setattr(atexit, "register", fake_register)

    yield

    while finalizers:
        func, args, kwargs = finalizers.pop()
        func(*args, **kwargs)


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--gx",
        action="append",
        dest="gspecs",
        help="add a global test environment, XSpec-syntax. ",
    )


@pytest.fixture
def specssh(request) -> str:
    return getspecssh(request.config)


# configuration information for tests
def getgspecs(config) -> List[execnet.XSpec]:
    return [execnet.XSpec(spec) for spec in config.getvalueorskip("gspecs")]


def getspecssh(config) -> str:  # type: ignore[return]
    xspecs = getgspecs(config)
    for spec in xspecs:
        if spec.ssh:
            if not shutil.which("ssh"):
                pytest.skip("command not found: ssh")
            return str(spec)
    pytest.skip("need '--gx ssh=...'")


def getsocketspec(config) -> execnet.XSpec:
    xspecs = getgspecs(config)
    for spec in xspecs:
        if spec.socket:
            return spec
    pytest.skip("need '--gx socket=...'")

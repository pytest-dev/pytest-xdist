from __future__ import annotations

import shutil
from typing import Callable
from typing import Generator

import execnet
import pytest


pytest_plugins = "pytester"


@pytest.fixture(autouse=True)
def _divert_atexit(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    import atexit

    finalizers = []

    def fake_register(
        func: Callable[..., object], *args: object, **kwargs: object
    ) -> None:
        finalizers.append((func, args, kwargs))

    monkeypatch.setattr(atexit, "register", fake_register)

    yield

    while finalizers:
        func, args, kwargs = finalizers.pop()
        func(*args, **kwargs)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--gx",
        action="append",
        dest="gspecs",
        help="add a global test environment, XSpec-syntax. ",
    )


@pytest.fixture
def specssh(request: pytest.FixtureRequest) -> str:
    return getspecssh(request.config)


# configuration information for tests
def getgspecs(config: pytest.Config) -> list[execnet.XSpec]:
    return [execnet.XSpec(spec) for spec in config.getvalueorskip("gspecs")]


def getspecssh(config: pytest.Config) -> str:
    xspecs = getgspecs(config)
    for spec in xspecs:
        if spec.ssh:
            if not shutil.which("ssh"):
                pytest.skip("command not found: ssh")
            return str(spec)
    pytest.skip("need '--gx ssh=...'")


def getsocketspec(config: pytest.Config) -> execnet.XSpec:
    xspecs = getgspecs(config)
    for spec in xspecs:
        if spec.socket:
            return spec
    pytest.skip("need '--gx socket=...'")

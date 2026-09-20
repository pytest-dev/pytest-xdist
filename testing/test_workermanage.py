from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil
import textwrap
from typing import Any
import warnings

import execnet
import pytest
from util import generate_warning

from xdist import workermanage
from xdist._path import visit_path
from xdist.remote import serialize_warning_message
from xdist.workermanage import HostRSync
from xdist.workermanage import NodeManager
from xdist.workermanage import unserialize_warning_message


pytest_plugins = "pytester"


@pytest.fixture
def hookrecorder(
    config: pytest.Config, pytester: pytest.Pytester
) -> pytest.HookRecorder:
    hookrecorder = pytester.make_hook_recorder(config.pluginmanager)
    return hookrecorder


@pytest.fixture
def config(pytester: pytest.Pytester) -> pytest.Config:
    return pytester.parseconfig()


@pytest.fixture
def source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    return source


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    dest = tmp_path / "dest"
    dest.mkdir()
    return dest


@pytest.fixture
def workercontroller(monkeypatch: pytest.MonkeyPatch) -> None:
    class MockController:
        def __init__(self, *args: object) -> None:
            pass

        def setup(self) -> None:
            pass

    monkeypatch.setattr(workermanage, "WorkerController", MockController)


class TestNodeManagerPopen:
    def test_popen_no_default_chdir(self, config: pytest.Config) -> None:
        gm = NodeManager(config, ["popen"])
        assert gm.specs[0].chdir is None

    def test_default_chdir(self, config: pytest.Config) -> None:
        specs = ["ssh=noco", "socket=xyz"]
        for spec in NodeManager(config, specs).specs:
            assert spec.chdir == "pyexecnetcache"
        for spec in NodeManager(config, specs, defaultchdir="abc").specs:
            assert spec.chdir == "abc"

    def test_popen_makegateway_events(
        self,
        config: pytest.Config,
        hookrecorder: pytest.HookRecorder,
        workercontroller: None,
    ) -> None:
        hm = NodeManager(config, ["popen"] * 2)
        hm.setup_nodes(None)  # type: ignore[arg-type]
        call = hookrecorder.popcall("pytest_xdist_setupnodes")
        assert len(call.specs) == 2

        call = hookrecorder.popcall("pytest_xdist_newgateway")
        assert call.gateway.spec == execnet.XSpec("execmodel=main_thread_only//popen")
        assert call.gateway.id == "gw0"
        call = hookrecorder.popcall("pytest_xdist_newgateway")
        assert call.gateway.id == "gw1"
        assert len(hm.group) == 2
        hm.teardown_nodes()
        assert not len(hm.group)

    def test_popen_makegateway_passes_stable_worker_index(
        self,
        config: pytest.Config,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        worker_indices: list[tuple[str, int]] = []

        class MockController:
            def __init__(
                self,
                nodemanager: NodeManager,
                gateway: execnet.Gateway,
                config: pytest.Config,
                putevent: object,
                worker_index: int,
            ) -> None:
                worker_indices.append((gateway.id, worker_index))

            def setup(self) -> None:
                pass

        monkeypatch.setattr(workermanage, "WorkerController", MockController)
        hm = NodeManager(config, ["popen//id=alpha", "popen//id=beta"])
        hm.setup_nodes(None)  # type: ignore[arg-type]

        assert worker_indices == [("alpha", 0), ("beta", 1)]

    def test_workerinput_includes_ramp_delay(self, config: pytest.Config) -> None:
        from xdist.workermanage import WorkerController

        class DummyManager:
            testrunuid = "testrun"
            specs = [execnet.XSpec("popen")] * 4

        class DummyGateway:
            id = "gw2"
            spec = execnet.XSpec("popen")

        config.option.ramp = 12.0
        node = WorkerController(
            nodemanager=DummyManager(),  # type: ignore[arg-type]
            gateway=DummyGateway(),  # type: ignore[arg-type]
            config=config,
            putevent=lambda event: None,
            worker_index=2,
        )

        assert node.workerinput["rampdelay"] == 6.0

    def test_popens_rsync(
        self,
        config: pytest.Config,
        source: Path,
        dest: Path,
        workercontroller: None,
    ) -> None:
        hm = NodeManager(config, ["popen"] * 2)
        hm.setup_nodes(None)  # type: ignore[arg-type]
        assert len(hm.group) == 2
        for gw in hm.group:

            class pseudoexec:
                args = []  # type: ignore[var-annotated]

                def __init__(self, *args: object) -> None:
                    self.args.extend(args)

                def waitclose(self) -> None:
                    pass

            gw.remote_exec = pseudoexec  # type: ignore[assignment]
        notifications = []
        for gw in hm.group:
            hm.rsync(gw, source, notify=lambda *args: notifications.append(args))
        assert not notifications
        hm.teardown_nodes()
        assert not len(hm.group)
        assert "sys.path.insert" in gw.remote_exec.args[0]  # type: ignore[attr-defined]

    def test_rsync_popen_with_path(
        self, config: pytest.Config, source: Path, dest: Path, workercontroller: None
    ) -> None:
        hm = NodeManager(config, ["popen//chdir=%s" % dest] * 1)
        hm.setup_nodes(None)  # type: ignore[arg-type]
        source.joinpath("dir1", "dir2").mkdir(parents=True)
        source.joinpath("dir1", "dir2", "hello").touch()
        notifications = []
        for gw in hm.group:
            hm.rsync(gw, source, notify=lambda *args: notifications.append(args))
        assert len(notifications) == 1
        assert notifications[0] == ("rsyncrootready", hm.group["gw0"].spec, source)
        hm.teardown_nodes()
        dest = dest.joinpath(source.name)
        assert dest.joinpath("dir1").exists()
        assert dest.joinpath("dir1", "dir2").exists()
        assert dest.joinpath("dir1", "dir2", "hello").exists()

    def test_rsync_same_popen_twice(
        self,
        config: pytest.Config,
        source: Path,
        dest: Path,
        hookrecorder: pytest.HookRecorder,
        workercontroller: None,
    ) -> None:
        hm = NodeManager(config, ["popen//chdir=%s" % dest] * 2)
        hm.roots = []
        hm.setup_nodes(None)  # type: ignore[arg-type]
        source.joinpath("dir1", "dir2").mkdir(parents=True)
        source.joinpath("dir1", "dir2", "hello").touch()
        gw = hm.group[0]
        hm.rsync(gw, source)
        call = hookrecorder.popcall("pytest_xdist_rsyncstart")
        assert call.source == source
        assert len(call.gateways) == 1
        assert call.gateways[0] in hm.group
        call = hookrecorder.popcall("pytest_xdist_rsyncfinish")


class TestHRSync:
    def test_hrsync_filter(self, source: Path, dest: Path) -> None:
        source.joinpath("dir").mkdir()
        source.joinpath("dir", "file.txt").touch()
        source.joinpath(".svn").mkdir()
        source.joinpath(".svn", "entries").touch()
        source.joinpath(".somedotfile").mkdir()
        source.joinpath(".somedotfile", "moreentries").touch()
        source.joinpath("somedir").mkdir()
        source.joinpath("somedir", "editfile~").touch()
        syncer = HostRSync(source, ignores=NodeManager.DEFAULT_IGNORES)
        files = list(visit_path(source, recurse=syncer.filter, filter=syncer.filter))
        names = {x.name for x in files}
        assert names == {"dir", "file.txt", "somedir"}

    def test_hrsync_one_host(self, source: Path, dest: Path) -> None:
        gw = execnet.makegateway("execmodel=main_thread_only//popen//chdir=%s" % dest)
        finished = []
        rsync = HostRSync(source)
        rsync.add_target_host(gw, finished=lambda: finished.append(1))
        source.joinpath("hello.py").write_text("world")
        rsync.send()
        gw.exit()
        assert dest.joinpath(source.name, "hello.py").exists()
        assert len(finished) == 1


class TestNodeManager:
    @pytest.mark.xfail(run=False)
    def test_rsync_roots_no_roots(
        self, pytester: pytest.Pytester, source: Path, dest: Path
    ) -> None:
        source.joinpath("dir1").mkdir()
        source.joinpath("dir1", "file1").write_text("hello")
        config = pytester.parseconfig(source)
        nodemanager = NodeManager(config, ["popen//chdir=%s" % dest])
        # assert nodemanager.config.topdir == source == config.topdir
        nodemanager.makegateways()  # type: ignore[attr-defined]
        nodemanager.rsync_roots()  # type: ignore[call-arg]
        (p,) = nodemanager.gwmanager.multi_exec(  # type: ignore[attr-defined]
            "import os ; channel.send(os.getcwd())"
        ).receive_each()
        p = Path(p)
        print("remote curdir", p)
        assert p == dest.joinpath(config.rootpath.name)
        assert p.joinpath("dir1").is_dir()
        assert p.joinpath("dir1", "file1").is_file()

    def test_popen_rsync_subdir(
        self,
        pytester: pytest.Pytester,
        source: Path,
        dest: Path,
        workercontroller: None,
    ) -> None:
        dir1 = source / "dir1"
        dir1.mkdir()
        dir2 = dir1 / "dir2"
        dir2.mkdir()
        dir2.joinpath("hello").touch()
        for rsyncroot in (dir1, source):
            shutil.rmtree(str(dest), ignore_errors=True)
            nodemanager = NodeManager(
                pytester.parseconfig(
                    "--tx", "popen//chdir=%s" % dest, "--rsyncdir", rsyncroot, source
                )
            )
            # calls .rsync_roots()
            nodemanager.setup_nodes(None)  # type: ignore[arg-type]
            if rsyncroot == source:
                dest = dest.joinpath("source")
            assert dest.joinpath("dir1").exists()
            assert dest.joinpath("dir1", "dir2").exists()
            assert dest.joinpath("dir1", "dir2", "hello").exists()
            nodemanager.teardown_nodes()

    @pytest.mark.parametrize(
        ["flag", "expects_report"],
        [
            ("-q", False),
            ("", False),
            ("-v", True),
        ],
    )
    def test_rsync_report(
        self,
        pytester: pytest.Pytester,
        source: Path,
        dest: Path,
        workercontroller: None,
        capsys: pytest.CaptureFixture[str],
        flag: str,
        expects_report: bool,
    ) -> None:
        dir1 = source / "dir1"
        dir1.mkdir()
        args = ["--tx", "popen//chdir=%s" % dest, "--rsyncdir", str(dir1), str(source)]
        if flag:
            args.append(flag)
        nodemanager = NodeManager(pytester.parseconfig(*args))
        # calls .rsync_roots()
        nodemanager.setup_nodes(None)  # type: ignore[arg-type]
        out, _ = capsys.readouterr()
        if expects_report:
            assert "<= pytest/__init__.py" in out
        else:
            assert "<= pytest/__init__.py" not in out

    def test_init_rsync_roots(
        self,
        pytester: pytest.Pytester,
        source: Path,
        dest: Path,
        workercontroller: None,
    ) -> None:
        dir2 = source.joinpath("dir1", "dir2")
        dir2.mkdir(parents=True)
        source.joinpath("dir1", "somefile").mkdir()
        dir2.joinpath("hello").touch()
        source.joinpath("bogusdir").mkdir()
        source.joinpath("bogusdir", "file").touch()
        source.joinpath("tox.ini").write_text(
            textwrap.dedent(
                """
                [pytest]
                rsyncdirs=dir1/dir2
                """
            )
        )
        config = pytester.parseconfig(source)
        nodemanager = NodeManager(config, ["popen//chdir=%s" % dest])
        # calls .rsync_roots()
        nodemanager.setup_nodes(None)  # type: ignore[arg-type]
        assert dest.joinpath("dir2").exists()
        assert not dest.joinpath("dir1").exists()
        assert not dest.joinpath("bogus").exists()

    def test_rsyncignore(
        self,
        pytester: pytest.Pytester,
        source: Path,
        dest: Path,
        workercontroller: None,
    ) -> None:
        dir2 = source.joinpath("dir1", "dir2")
        dir2.mkdir(parents=True)
        source.joinpath("dir5", "dir6").mkdir(parents=True)
        source.joinpath("dir5", "dir6", "bogus").touch()
        source.joinpath("dir5", "file").touch()
        dir2.joinpath("hello").touch()
        source.joinpath("foo").mkdir()
        source.joinpath("foo", "bar").touch()
        source.joinpath("bar").mkdir()
        source.joinpath("bar", "foo").touch()
        source.joinpath("tox.ini").write_text(
            textwrap.dedent(
                """
                [pytest]
                rsyncdirs = dir1 dir5
                rsyncignore = dir1/dir2 dir5/dir6 foo*
                """
            )
        )
        config = pytester.parseconfig(source)
        config.option.rsyncignore = ["bar"]
        nodemanager = NodeManager(config, ["popen//chdir=%s" % dest])
        # calls .rsync_roots()
        nodemanager.setup_nodes(None)  # type: ignore[arg-type]
        assert dest.joinpath("dir1").exists()
        assert not dest.joinpath("dir1", "dir2").exists()
        assert dest.joinpath("dir5", "file").exists()
        assert not dest.joinpath("dir6").exists()
        assert not dest.joinpath("foo").exists()
        assert not dest.joinpath("bar").exists()

    def test_optimise_popen(
        self,
        pytester: pytest.Pytester,
        source: Path,
        dest: Path,
        workercontroller: None,
    ) -> None:
        specs = ["popen"] * 3
        source.joinpath("conftest.py").write_text("rsyncdirs = ['a']")
        source.joinpath("a").mkdir()
        config = pytester.parseconfig(source)
        nodemanager = NodeManager(config, specs)
        # calls .rysnc_roots()
        nodemanager.setup_nodes(None)  # type: ignore[arg-type]
        for gwspec in nodemanager.specs:
            assert gwspec._samefilesystem()
            assert not gwspec.chdir

    def test_ssh_setup_nodes(self, specssh: str, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(
            __init__="",
            test_x="""
            def test_one():
                pass
        """,
        )
        reprec = pytester.inline_run(
            "-d", "--rsyncdir=%s" % pytester.path, "--tx", specssh, pytester.path
        )
        (rep,) = reprec.getreports("pytest_runtest_logreport")
        assert rep.passed

    def test_proxy_gateway_setup_nodes(self, pytester: pytest.Pytester) -> None:
        nodemanager = NodeManager(
            pytester.parseconfig(
                "--px", "popen//id=my_proxy", "--tx", "popen//via=my_proxy"
            )
        )
        nodes = nodemanager.setup_nodes(None)  # type: ignore[arg-type]

        # Proxy gateways are considered as an execnet gateway
        assert len(nodemanager.group) == 2

        # Proxy gateways do not run workers
        assert len(nodes) == 1

    def test_proxy_gateway(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(
            __init__="",
            test_x="""
            def test_one():
                pass
        """,
        )
        reprec = pytester.inline_run(
            "-d", "--px", "popen//id=my_proxy", "--tx", "popen//via=my_proxy"
        )
        rep = reprec.getreports("pytest_runtest_logreport")
        assert rep[1].passed


class MyWarning(UserWarning):
    pass


@pytest.mark.parametrize(
    "w_cls",
    [
        UserWarning,
        MyWarning,
        "Imported",
        pytest.param(
            "Nested",
            marks=pytest.mark.xfail(reason="Nested warning classes are not supported."),
        ),
    ],
)
def test_unserialize_warning_msg(w_cls: type[Warning] | str) -> None:
    """Test that warning serialization process works well."""
    # Create a test warning message
    with pytest.warns(UserWarning) as w:
        if not isinstance(w_cls, str):
            warnings.warn("hello", w_cls)
        elif w_cls == "Imported":
            generate_warning()
        elif w_cls == "Nested":
            # dynamic creation
            class MyWarning2(UserWarning):
                pass

            warnings.warn("hello", MyWarning2)

    # Unpack
    assert len(w) == 1
    w_msg = w[0]

    # Serialize and deserialize
    data = serialize_warning_message(w_msg)
    w_msg2 = unserialize_warning_message(data)

    # Compare the two objects
    all_keys = set(vars(w_msg).keys()).union(set(vars(w_msg2).keys()))
    for k in all_keys:
        v1 = getattr(w_msg, k)
        v2 = getattr(w_msg2, k)
        if k == "message":
            assert type(v1) is type(v2)
            assert v1.args == v2.args
        else:
            assert v1 == v2


class WarningWithFieldFirst(UserWarning):
    """First argument is a field; the message is rendered from it."""

    def __init__(self, resource: str) -> None:
        self.resource = resource
        super().__init__(f"{resource!r} is not available")


class WarningWithSlots(UserWarning):
    """Keeps its state in slots, which `BaseException.__reduce__` never reports."""

    __slots__ = ("code",)

    def __init__(self, code: int | None = None) -> None:
        self.code = code
        super().__init__()

    def __str__(self) -> str:
        return f"code {self.code or 'unknown'} tripped"


class WarningWithoutArgs(UserWarning):
    """No args at all; the text is derived from state."""

    def __init__(self, code: int | None = None) -> None:
        self.code = code
        super().__init__()

    def __str__(self) -> str:
        return f"code {self.code or 'unknown'} tripped"


def _rebuild_with_own_callable(code: int) -> WarningWithCustomReduce:
    return WarningWithCustomReduce(code)


class WarningWithCustomReduce(UserWarning):
    """Replaces `__reduce__`, and carries its state inside the *args*."""

    def __init__(self, code: int | None = None) -> None:
        self.code = code
        super().__init__()

    def __str__(self) -> str:
        return f"code {self.code or 'unknown'} tripped"

    def __reduce__(self) -> tuple[Any, ...]:
        return (_rebuild_with_own_callable, (self.code,))


@pytest.mark.parametrize(
    ("factory", "expected_text", "attribute", "expected_value"),
    [
        (
            lambda: WarningWithFieldFirst("gpu"),
            "'gpu' is not available",
            "resource",
            "gpu",
        ),
        (lambda: WarningWithoutArgs(42), "code 42 tripped", "code", 42),
        (lambda: WarningWithSlots(11), "code 11 tripped", "code", 11),
        (lambda: WarningWithCustomReduce(7), "code 7 tripped", "code", 7),
    ],
    ids=["field-first", "state-only", "slots", "custom-reduce"],
)
def test_warning_state_survives_the_round_trip(
    factory: Callable[[], UserWarning],
    expected_text: str,
    attribute: str,
    expected_value: object,
) -> None:
    """The rebuilt warning must be the same warning, not one that reads like it.

    Calling the class with its own `args` re-runs `__init__`, which for these two
    shapes either renders around the rendered text or falls back to a default.
    Both survive `pickle` and `copy` untouched, so the loss was ours.
    """
    with pytest.warns(UserWarning) as w:
        warnings.warn(factory())

    assert len(w) == 1
    w_msg = w[0]
    assert str(w_msg.message) == expected_text

    data = serialize_warning_message(w_msg)
    rebuilt = unserialize_warning_message(data).message

    assert type(rebuilt) is type(w_msg.message)
    assert str(rebuilt) == expected_text
    assert getattr(rebuilt, attribute) == expected_value


class WarningWithUntransferableState(UserWarning):
    """Keeps something `execnet.dumps` will not carry."""

    def __init__(self, code: int | None = None) -> None:
        self.code = code
        self.handle = lambda: None
        super().__init__()

    def __str__(self) -> str:
        return f"code {self.code or 'unknown'} tripped"


def test_state_that_cannot_transfer_falls_back_to_a_plain_warning() -> None:
    """Rebuilding the class without its state is worse than not rebuilding it.

    This shape keeps state its own `__str__` reads, and that state is not
    serializable. Rebuilding the class and applying no state produces an instance
    missing the attribute, and the controller raises `AttributeError` the moment it
    renders the warning -- a failure introduced while fixing a rendering defect.
    So the class is dropped and the text is reported once.
    """
    with pytest.warns(UserWarning) as w:
        warnings.warn(WarningWithUntransferableState(9))

    original = w[0].message
    rebuilt = unserialize_warning_message(serialize_warning_message(w[0])).message

    assert type(rebuilt) is Warning
    assert str(original) in str(rebuilt)


def test_a_warning_keeping_no_state_is_still_rebuilt_exactly() -> None:
    """The fallback must not widen to warnings that have nothing to lose.

    A warning holding nothing beside its `args` reduces to a two-tuple. There is
    no state, so there is nothing to fail to transfer, and dropping its class
    would cost the caller its type for no reason.
    """
    with pytest.warns(UserWarning) as w:
        warnings.warn(UserWarning("plain text"))

    rebuilt = unserialize_warning_message(serialize_warning_message(w[0])).message

    assert type(rebuilt) is UserWarning
    assert str(rebuilt) == "plain text"


class MyWarningUnknown(UserWarning):
    # Changing the __module__ attribute is only safe if class can be imported
    # from there
    __module__ = "unknown"


def test_warning_serialization_tweaked_module() -> None:
    """Test for GH#404."""
    # Create a test warning message
    with pytest.warns(UserWarning) as w:
        warnings.warn("hello", MyWarningUnknown)

    # Unpack
    assert len(w) == 1
    w_msg = w[0]

    # Serialize and deserialize
    data = serialize_warning_message(w_msg)

    # __module__ cannot be found!
    with pytest.raises(ModuleNotFoundError):
        unserialize_warning_message(data)

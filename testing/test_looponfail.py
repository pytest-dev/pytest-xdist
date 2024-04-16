from __future__ import annotations

import pathlib
from pathlib import Path
import shutil
import tempfile
import textwrap
import unittest.mock

import pytest

from xdist.looponfail import RemoteControl
from xdist.looponfail import StatRecorder


class TestStatRecorder:
    def test_filechange(self, tmp_path: Path) -> None:
        tmp = tmp_path
        hello = tmp / "hello.py"
        hello.touch()
        sd = StatRecorder([tmp])
        changed = sd.check()
        assert not changed

        hello.write_text("world")
        changed = sd.check()
        assert changed

        hello.with_suffix(".pyc").write_text("hello")
        changed = sd.check()
        assert not changed

        p = tmp / "new.py"
        p.touch()
        changed = sd.check()
        assert changed

        p.unlink()
        changed = sd.check()
        assert changed

        tmp.joinpath("a", "b").mkdir(parents=True)
        tmp.joinpath("a", "b", "c.py").touch()
        changed = sd.check()
        assert changed

        tmp.joinpath("a", "c.txt").touch()
        changed = sd.check()
        assert changed
        changed = sd.check()
        assert not changed

        shutil.rmtree(str(tmp.joinpath("a")))
        changed = sd.check()
        assert changed

    def test_dirchange(self, tmp_path: Path) -> None:
        tmp = tmp_path
        tmp.joinpath("dir").mkdir()
        tmp.joinpath("dir", "hello.py").touch()
        sd = StatRecorder([tmp])
        assert not sd.fil(tmp / "dir")

    def test_filechange_deletion_race(self, tmp_path: Path) -> None:
        tmp = tmp_path
        sd = StatRecorder([tmp])
        changed = sd.check()
        assert not changed

        p = tmp.joinpath("new.py")
        p.touch()
        changed = sd.check()
        assert changed

        p.unlink()
        # make check()'s visit() call return our just removed
        # path as if we were in a race condition
        dirname = str(tmp)
        dirnames: list[str] = []
        filenames = [str(p)]
        with unittest.mock.patch(
            "os.walk", return_value=[(dirname, dirnames, filenames)], autospec=True
        ):
            changed = sd.check()
        assert changed

    def test_pycremoval(self, tmp_path: Path) -> None:
        tmp = tmp_path
        hello = tmp / "hello.py"
        hello.touch()
        sd = StatRecorder([tmp])
        changed = sd.check()
        assert not changed

        pycfile = hello.with_suffix(".pyc")
        pycfile.touch()
        hello.write_text("world")
        changed = sd.check()
        assert changed
        assert not pycfile.exists()

    def test_waitonchange(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tmp = tmp_path
        sd = StatRecorder([tmp])

        ret_values = [True, False]
        monkeypatch.setattr(StatRecorder, "check", lambda self: ret_values.pop())
        sd.waitonchange(checkinterval=0.2)
        assert not ret_values


class TestRemoteControl:
    def test_nofailures(self, pytester: pytest.Pytester) -> None:
        item = pytester.getitem("def test_func(): pass\n")
        control = RemoteControl(item.config)
        control.setup()
        topdir, failures = control.runsession()[:2]
        assert not failures

    def test_failures_somewhere(self, pytester: pytest.Pytester) -> None:
        item = pytester.getitem("def test_func():\n assert 0\n")
        control = RemoteControl(item.config)
        control.setup()
        failures = control.runsession()[0]
        assert failures
        control.setup()
        item.path.write_text("def test_func():\n assert 1\n")
        removepyc(item.path)
        topdir, failures = control.runsession()[:2]
        assert not failures

    def test_failure_change(self, pytester: pytest.Pytester) -> None:
        modcol = pytester.getitem(
            textwrap.dedent(
                """
                def test_func():
                    assert 0
                """
            )
        )
        control = RemoteControl(modcol.config)
        control.loop_once()
        assert control.failures
        modcol_path = modcol.path

        modcol_path.write_text(
            textwrap.dedent(
                """
                def test_func():
                    assert 1
                def test_new():
                    assert 0
                """
            )
        )
        removepyc(modcol_path)
        control.loop_once()
        assert not control.failures
        control.loop_once()
        assert control.failures
        assert str(control.failures).find("test_new") != -1

    def test_failure_subdir_no_init(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        modcol = pytester.getitem(
            textwrap.dedent(
                """
                def test_func():
                    assert 0
                """
            )
        )
        parent = modcol.path.parent.parent
        monkeypatch.chdir(parent)
        modcol.config.args = [
            str(Path(x).relative_to(parent)) for x in modcol.config.args
        ]
        control = RemoteControl(modcol.config)
        control.loop_once()
        assert control.failures
        control.loop_once()
        assert control.failures

    def test_ignore_sys_path_hook_entry(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Modifying sys.path as seen by the worker process is a bit tricky,
        # because any changes made in the current process do not carry over.
        # However, we can leverage the `sitecustomize` behavior to run arbitrary
        # code when the subprocess interpreter is starting up. We just need to
        # install our module in the search path, which we can accomplish by
        # adding a temporary directory to PYTHONPATH.
        tmpdir = tempfile.TemporaryDirectory()
        with open(pathlib.Path(tmpdir.name) / "sitecustomize.py", "w") as custom:
            print(
                textwrap.dedent(
                    """
                    import sys
                    sys.path.append('dummy.__path_hook__')
                    """
                ),
                file=custom,
            )

        monkeypatch.setenv("PYTHONPATH", tmpdir.name, prepend=":")

        item = pytester.getitem(
            textwrap.dedent(
                """
                def test_func():
                    import sys
                    assert "dummy.__path_hook__" in sys.path
                """
            )
        )
        control = RemoteControl(item.config)
        control.setup()
        topdir, failures = control.runsession()[:2]
        assert not failures


class TestLooponFailing:
    def test_looponfail_from_fail_to_ok(self, pytester: pytest.Pytester) -> None:
        modcol = pytester.getmodulecol(
            textwrap.dedent(
                """
                def test_one():
                    x = 0
                    assert x == 1
                def test_two():
                    assert 1
                """
            )
        )
        remotecontrol = RemoteControl(modcol.config)
        remotecontrol.loop_once()
        assert len(remotecontrol.failures) == 1

        modcol.path.write_text(
            textwrap.dedent(
                """
                def test_one():
                    assert 1
                def test_two():
                    assert 1
                """
            )
        )
        removepyc(modcol.path)
        remotecontrol.loop_once()
        assert not remotecontrol.failures

    def test_looponfail_from_one_to_two_tests(self, pytester: pytest.Pytester) -> None:
        modcol = pytester.getmodulecol(
            textwrap.dedent(
                """
                def test_one():
                    assert 0
                """
            )
        )
        remotecontrol = RemoteControl(modcol.config)
        remotecontrol.loop_once()
        assert len(remotecontrol.failures) == 1
        assert "test_one" in remotecontrol.failures[0]

        modcol.path.write_text(
            textwrap.dedent(
                """
                def test_one():
                    assert 1 # passes now
                def test_two():
                    assert 0 # new and fails
                """
            )
        )
        removepyc(modcol.path)
        remotecontrol.loop_once()
        assert len(remotecontrol.failures) == 0
        remotecontrol.loop_once()
        assert len(remotecontrol.failures) == 1
        assert "test_one" not in remotecontrol.failures[0]
        assert "test_two" in remotecontrol.failures[0]

    @pytest.mark.xfail(reason="broken by pytest 3.1+", strict=True)
    def test_looponfail_removed_test(self, pytester: pytest.Pytester) -> None:
        modcol = pytester.getmodulecol(
            textwrap.dedent(
                """
                def test_one():
                    assert 0
                def test_two():
                    assert 0
                """
            )
        )
        remotecontrol = RemoteControl(modcol.config)
        remotecontrol.loop_once()
        assert len(remotecontrol.failures) == 2

        modcol.path.write_text(
            textwrap.dedent(
                """
                def test_xxx(): # renamed test
                    assert 0
                def test_two():
                    assert 1 # pass now
                """
            )
        )
        removepyc(modcol.path)
        remotecontrol.loop_once()
        assert len(remotecontrol.failures) == 0

        remotecontrol.loop_once()
        assert len(remotecontrol.failures) == 1

    def test_looponfail_multiple_errors(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        modcol = pytester.getmodulecol(
            textwrap.dedent(
                """
                def test_one():
                    assert 0
                """
            )
        )
        remotecontrol = RemoteControl(modcol.config)
        orig_runsession = remotecontrol.runsession

        def runsession_dups() -> tuple[list[str], list[str], bool]:
            # twisted.trial test cases may report multiple errors.
            failures, reports, collection_failed = orig_runsession()
            print(failures)
            return failures * 2, reports, collection_failed

        monkeypatch.setattr(remotecontrol, "runsession", runsession_dups)
        remotecontrol.loop_once()
        assert len(remotecontrol.failures) == 1


class TestFunctional:
    def test_fail_to_ok(self, pytester: pytest.Pytester) -> None:
        p = pytester.makepyfile(
            textwrap.dedent(
                """
                def test_one():
                    x = 0
                    assert x == 1
                """
            )
        )
        # p = pytester.mkdir("sub").join(p1.basename)
        # p1.move(p)
        child = pytester.spawn_pytest("-f %s --traceconfig" % p, expect_timeout=30.0)
        child.expect("def test_one")
        child.expect("x == 1")
        child.expect("1 failed")
        child.expect("### LOOPONFAILING ####")
        child.expect("waiting for changes")
        p.write_text(
            textwrap.dedent(
                """
                def test_one():
                    x = 1
                    assert x == 1
                """
            ),
        )
        child.expect(".*1 passed.*")
        child.kill(15)

    def test_xfail_passes(self, pytester: pytest.Pytester) -> None:
        p = pytester.makepyfile(
            textwrap.dedent(
                """
                import pytest
                @pytest.mark.xfail
                def test_one():
                    pass
                """
            )
        )
        child = pytester.spawn_pytest("-f %s" % p, expect_timeout=30.0)
        child.expect("1 xpass")
        # child.expect("### LOOPONFAILING ####")
        child.expect("waiting for changes")
        child.kill(15)


def removepyc(path: Path) -> None:
    # XXX damn those pyc files
    pyc = path.with_suffix(".pyc")
    if pyc.exists():
        pyc.unlink()
    c = path.parent / "__pycache__"
    if c.exists():
        shutil.rmtree(c)

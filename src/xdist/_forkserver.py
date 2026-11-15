"""Experimental controller and workers using multiprocessing's forkserver."""

from __future__ import annotations

import argparse
import json
import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.connection import wait
from multiprocessing.process import BaseProcess
from multiprocessing.reduction import recv_handle
from multiprocessing.reduction import send_handle
import os
from pathlib import Path
import shutil
import signal
import socket
import sys
import tempfile
import threading
import traceback

import execnet
from execnet.gateway_base import get_execmodel
from execnet.gateway_base import serve
from execnet.gateway_socket import SocketIO
import pytest


forkserver_key = pytest.StashKey["Forkserver"]()
session_key = pytest.StashKey["ForkserverSession"]()
PRELOAD_ENV = "_PYTEST_XDIST_FORKSERVER_PRELOAD"
preloading = False


def _validate_spec(spec: execnet.XSpec) -> None:
    if (
        not spec.popen
        or spec.python
        or spec.via
        or spec.chdir
        or spec.env
        or spec.nice
        or spec.dont_write_bytecode
        or spec.execmodel not in (None, "main_thread_only")
    ):
        raise pytest.UsageError(
            "forkserver requires local popen workers using the current interpreter "
            "and the main_thread_only execution model, without per-worker settings"
        )


def start_forkserver(
    config: pytest.Config, options: argparse.Namespace | None = None
) -> None:
    if "forkserver" not in multiprocessing.get_all_start_methods():
        raise pytest.UsageError("forkserver workers require Unix forkserver support")
    if options is None:
        options = config.option
    if options.px:
        raise pytest.UsageError("forkserver workers do not support proxy gateways")
    for entry in ["popen"] if options.numprocesses else options.tx:
        prefix, separator, spec = entry.partition("*")
        try:
            int(prefix)
        except ValueError:
            spec = entry
        else:
            if not separator:
                spec = entry
        _validate_spec(execnet.XSpec(spec))
    plugins = config.invocation_params.plugins
    if plugins and any(not isinstance(plugin, str) for plugin in plugins):
        raise pytest.UsageError(
            "forkserver requires plugins passed to pytest.main() to be module names"
        )
    session = ForkserverSession(
        {
            "args": config.invocation_params.args,
            "plugins": plugins,
            "sys_path": sys.path,
            "argv": sys.argv,
            "cwd": str(config.invocation_params.dir),
        }
    )
    config.stash[session_key] = session
    config.add_cleanup(session.close)


class ForkserverSession:
    def __init__(self, preparation: dict[str, object]) -> None:
        # A spawned helper owns the multiprocessing context. Embedded pytest
        # calls leave the launcher's forkserver and preload settings unchanged.
        self.directory = tempfile.TemporaryDirectory(prefix="xdist-fork-")
        preparation_path = Path(self.directory.name) / "preload.json"
        preparation_path.write_text(json.dumps(preparation), encoding="utf-8")
        context = multiprocessing.get_context("spawn")
        self.control, remote = context.Pipe()
        self.process = context.Process(
            target=_supervise, args=(remote, preparation_path), name="xdist-forkserver"
        )
        try:
            self.process.start()
            remote.close()
            error = self.control.recv()
            if error is not None:
                raise pytest.UsageError(error)
        except BaseException:
            remote.close()
            self.close()
            raise

    def run(self) -> int:
        self.control.send("run")
        try:
            result = self.control.recv()
        except KeyboardInterrupt:
            self.control.send("interrupt")
            result = self.control.recv()
        if not isinstance(result, int):
            raise pytest.UsageError(result)
        return result

    def close(self) -> None:
        try:
            # EOF also asks the helper to clean up after abrupt launcher exit.
            self.control.close()
            if self.process.pid is not None:
                self.process.join(10)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(10)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join()
                self.process.close()
        finally:
            self.directory.cleanup()


def _check_preload() -> None:
    """Starting this child ensures preloading has finished before pytest continues."""


def _supervise(control: Connection, preparation_path: Path) -> None:
    workers: dict[int, BaseProcess] = {}
    controller: BaseProcess | None = None
    requests: Connection | None = None

    def terminate(signum: int, frame: object) -> None:
        raise SystemExit(1)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        context = multiprocessing.get_context("forkserver")
        context.set_forkserver_preload(["xdist._forkserver_preload"])
        os.environ[PRELOAD_ENV] = str(preparation_path)
        probe = context.Process(target=_check_preload)
        try:
            probe.start()
            probe.join()
            if probe.exitcode != 0:
                raise RuntimeError("forkserver preload probe failed")
            probe.close()
        except (OSError, EOFError, RuntimeError):
            error_path = preparation_path.with_name("error.txt")
            if error_path.exists():
                control.send(error_path.read_text(encoding="utf-8"))
                return
            raise
        finally:
            os.environ.pop(PRELOAD_ENV, None)
        control.send(None)
        if control.recv() != "run":
            return
        requests, remote = context.Pipe()
        controller = context.Process(
            target=_run_controller, args=(remote, os.getpid()), name="xdist-controller"
        )
        controller.start()
        remote.close()
        while True:
            watched: list[Connection | int] = [control, controller.sentinel]
            if requests is not None:
                watched.append(requests)
            ready = wait(watched)
            if control in ready:
                if control.recv() == "interrupt":
                    assert controller.pid is not None
                    os.kill(controller.pid, signal.SIGINT)
            if requests is not None and requests in ready:
                try:
                    command, value = requests.recv()
                except EOFError:
                    requests.close()
                    requests = None
                else:
                    if command == "start":
                        connection = socket.socket(fileno=recv_handle(requests))
                        try:
                            worker: BaseProcess = context.Process(
                                target=_serve_worker,
                                args=(connection, value),
                                name=f"xdist-{value}",
                            )
                            worker.start()
                            assert worker.pid is not None
                            workers[worker.pid] = worker
                            requests.send(worker.pid)
                        finally:
                            connection.close()
                    elif command == "kill":
                        running_worker = workers.get(value)
                        if running_worker is not None and running_worker.is_alive():
                            running_worker.kill()
                        requests.send(None)
            if controller.sentinel in ready:
                controller.join()
                assert controller.exitcode is not None
                control.send(
                    controller.exitcode
                    if controller.exitcode >= 0
                    else int(pytest.ExitCode.INTERNAL_ERROR)
                )
                return
            for pid, worker in list(workers.items()):
                if worker.exitcode is not None:
                    worker.join()
                    worker.close()
                    del workers[pid]
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        try:
            control.send(traceback.format_exc())
        except (BrokenPipeError, OSError):
            pass
    finally:
        control.close()
        if requests is not None:
            requests.close()
        for process in [*workers.values(), *([controller] if controller else [])]:
            if process.is_alive():
                process.kill()
            process.join()
            process.close()
        # The launcher cannot run its TemporaryDirectory finalizer after SIGKILL.
        shutil.rmtree(preparation_path.parent, ignore_errors=True)


def _run_controller(control: Connection, supervisor_pid: int) -> None:
    from xdist._forkserver_preload import config

    signal.signal(signal.SIGINT, signal.default_int_handler)
    _start_capture()
    server = Forkserver(control, supervisor_pid)
    config.stash[forkserver_key] = server
    config.add_cleanup(server.close)
    try:
        try:
            result = config.hook.pytest_cmdline_main(config=config)
        finally:
            config._ensure_unconfigure()
    except pytest.UsageError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        result = pytest.ExitCode.USAGE_ERROR
    raise SystemExit(result)


class Forkserver:
    def __init__(self, control: Connection, supervisor_pid: int) -> None:
        self.control = control
        self.supervisor_pid = supervisor_pid
        self.lock = threading.Lock()

    def connect(self, gateway_id: str) -> ForkIO:
        local, remote = socket.socketpair()
        try:
            with self.lock:
                self.control.send(("start", gateway_id))
                send_handle(self.control, remote.fileno(), self.supervisor_pid)
                pid = self.control.recv()
            return ForkIO(local, self, pid)
        except BaseException:
            local.close()
            raise
        finally:
            remote.close()

    def kill(self, pid: int) -> None:
        with self.lock:
            self.control.send(("kill", pid))
            self.control.recv()

    def close(self) -> None:
        self.control.close()


def _serve_worker(connection: socket.socket, gateway_id: str) -> None:
    with open(os.devnull, "r+b") as devnull:
        os.dup2(devnull.fileno(), 0)
        os.dup2(devnull.fileno(), 1)
    _start_capture()
    serve(ForkIO(connection), id=f"{gateway_id}-worker")


def _start_capture() -> None:
    from xdist._forkserver_preload import config

    capture = config.pluginmanager.getplugin("capturemanager")
    if capture is not None:
        capture.start_global_capturing()
        capture.suspend_global_capture()


class ForkIO(SocketIO):
    def __init__(
        self,
        connection: socket.socket,
        server: Forkserver | None = None,
        pid: int | None = None,
    ) -> None:
        # SocketIO otherwise tries to set TCP options on the Unix socket.
        self.sock = connection
        self.execmodel = get_execmodel("main_thread_only")
        self.server = server
        self.pid = pid

    def kill(self) -> None:
        if self.server is not None and self.pid is not None:
            self.server.kill(self.pid)


class ForkserverGroup(execnet.Group):
    def __init__(self, server: Forkserver) -> None:
        super().__init__(execmodel="main_thread_only")
        self.server = server

    def makegateway(self, spec: execnet.XSpec | str | None = None) -> execnet.Gateway:
        if not isinstance(spec, execnet.XSpec):
            spec = execnet.XSpec(spec or self.defaultspec)
        _validate_spec(spec)
        self.allocate_id(spec)
        assert isinstance(spec.id, str)
        gateway = execnet.Gateway(self.server.connect(spec.id), spec)
        # Keep execnet's normal gateway shutdown and worker restart machinery.
        # This is the remaining seam to replace with an execnet gateway factory.
        self._register(gateway)
        return gateway

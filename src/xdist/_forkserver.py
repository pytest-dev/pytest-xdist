"""Experimental local fork transport. All execnet internals are isolated here.

The server is a fresh interpreter, never an execnet gateway. In particular it
must not acquire a receiver thread before forking.
"""

from __future__ import annotations

import gc
from multiprocessing.connection import Connection
from multiprocessing.reduction import recv_handle
from multiprocessing.reduction import send_handle
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
from typing import Any

import execnet
from execnet.gateway_base import get_execmodel
from execnet.gateway_base import Popen2IO
from execnet.gateway_base import serve as serve_gateway
import pytest


_prepared_config: pytest.Config | None = None


def take_config() -> pytest.Config:
    global _prepared_config
    assert _prepared_config is not None
    config = _prepared_config
    _prepared_config = None
    return config


def _check_threads() -> None:
    import psutil

    if psutil.Process().num_threads() != 1:
        raise RuntimeError(
            "forkserver preload started background threads; cannot fork safely"
        )


def serve(fd: int) -> None:
    global _prepared_config
    control = Connection(fd)
    children: dict[int, int | None] = {}
    try:
        args, search_path, environment = control.recv()
        sys.path[:] = search_path
        os.environ.pop("PYTEST_XDIST_WORKER", None)
        os.environ.update(environment)
        os.environ["PYTEST_XDIST_PRELOAD"] = "1"
        from _pytest.config import _prepareconfig

        gc.disable()
        _prepared_config = _prepareconfig(args, None)
        capture = _prepared_config.pluginmanager.getplugin("capturemanager")
        if capture is not None:
            capture.stop_global_capturing()
        _check_threads()
        gc.collect()
        gc.freeze()
        control.send((True, None))
        while True:
            command, value = control.recv()
            if command == "spawn":
                _check_threads()
                parent, child = socket.socketpair()
                pid = os.fork()
                if pid == 0:
                    try:
                        control.close()
                        parent.close()
                        os.environ.pop("PYTEST_XDIST_PRELOAD", None)
                        gc.enable()
                        if capture is not None:
                            capture.start_global_capturing()
                            capture.suspend_global_capture()
                        model = get_execmodel("main_thread_only")
                        io = Popen2IO(child.makefile("wb"), child.makefile("rb"), model)
                        serve_gateway(io, id=value + "-worker")  # type: ignore[arg-type]
                    except BaseException:
                        traceback.print_exc()
                        os._exit(1)
                    os._exit(0)
                child.close()
                children[pid] = None
                control.send((True, pid))
                send_handle(control, parent.fileno(), os.getppid())
                parent.close()
            elif command == "poll":
                status = children[value]
                if status is None:
                    pid, raw = os.waitpid(value, os.WNOHANG)
                    if pid:
                        status = os.waitstatus_to_exitcode(raw)
                        children[value] = status
                control.send((True, status))
            elif command == "kill":
                if children[value] is None:
                    try:
                        os.kill(value, 9)
                    except ProcessLookupError:
                        pass
                control.send((True, None))
            elif command == "close":
                break
    except EOFError:
        pass
    except BaseException:
        try:
            control.send((False, traceback.format_exc()))
        except (OSError, EOFError):
            pass
    finally:
        for pid, status in children.items():
            if status is None:
                try:
                    os.kill(pid, 9)
                    os.waitpid(pid, 0)
                except (ProcessLookupError, ChildProcessError):
                    pass
        if _prepared_config is not None:
            _prepared_config._ensure_unconfigure()
        control.close()


class ForkIO(Popen2IO):
    def __init__(
        self, sock: socket.socket, server: ForkServer, pid: int, model: Any
    ) -> None:
        super().__init__(sock.makefile("wb"), sock.makefile("rb"), model)
        sock.close()
        self.server = server
        self.pid = pid

    def wait(self) -> int:
        while True:
            status = self.server.request("poll", self.pid)
            if status is not None:
                return int(status)
            time.sleep(0.02)

    def kill(self) -> None:
        self.server.request("kill", self.pid)


class ForkServer:
    def __init__(
        self, config: pytest.Config, testrunuid: str, workercount: int
    ) -> None:
        if sys.platform not in ("linux", "darwin"):
            raise pytest.UsageError("forkserver is supported only on Linux and macOS")
        try:
            import psutil  # noqa: F401
        except ImportError as exc:
            raise pytest.UsageError("forkserver requires pytest-xdist[psutil]") from exc
        parent, child = socket.socketpair()
        self.control = Connection(parent.detach())
        self.lock = threading.Lock()
        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "from xdist._forkserver import serve; import sys; serve(int(sys.argv[1]))",
                    str(child.fileno()),
                ],
                pass_fds=(child.fileno(),),
                stdout=subprocess.DEVNULL,
            )
        except BaseException:
            child.close()
            self.control.close()
            raise
        child.close()
        try:
            self.control.send(
                (
                    list(config.invocation_params.args),
                    list(sys.path),
                    {
                        "PYTEST_XDIST_TESTRUNUID": testrunuid,
                        "PYTEST_XDIST_WORKER_COUNT": str(workercount),
                    },
                )
            )
            self._receive()
        except BaseException:
            self.close()
            raise

    def _receive(self) -> Any:
        if not self.control.poll(60):
            raise pytest.UsageError("forkserver did not respond within 60 seconds")
        try:
            success, result = self.control.recv()
        except EOFError as exc:
            raise pytest.UsageError("forkserver exited unexpectedly") from exc
        if not success:
            raise pytest.UsageError("forkserver failed:\n" + result)
        return result

    def request(self, command: str, value: Any = None) -> Any:
        with self.lock:
            self.control.send((command, value))
            return self._receive()

    def makegateway(self, group: execnet.Group, spec: execnet.XSpec) -> execnet.Gateway:
        with self.lock:
            self.control.send(("spawn", spec.id))
            pid = self._receive()
            fd = recv_handle(self.control)
        io = ForkIO(socket.socket(fileno=fd), self, pid, group.execmodel)
        gateway = execnet.Gateway(io, spec)
        group._register(gateway)
        return gateway

    def close(self) -> None:
        try:
            self.control.send(("close", None))
        except OSError:
            pass
        self.control.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

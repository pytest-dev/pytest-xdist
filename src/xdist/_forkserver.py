"""Experimental local workers inheriting imports from an early pytest snapshot."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import socket
import struct
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


def start_forkserver(config: pytest.Config) -> None:
    from xdist.workermanage import parse_tx_spec_config

    if not hasattr(os, "fork") or not hasattr(socket, "AF_UNIX"):
        raise pytest.UsageError("forkserver workers require Unix fork support")
    if config.getoption("px"):
        raise pytest.UsageError("forkserver workers do not support proxy gateways")
    for spec in parse_tx_spec_config(config):
        _validate_spec(execnet.XSpec(spec))
    config.hook.pytest_xdist_before_fork(config=config)
    if threading.active_count() != 1:
        raise pytest.UsageError(
            "forkserver workers require single-threaded imports; stop background "
            "threads in pytest_xdist_before_fork"
        )
    sys.stdout.flush()
    sys.stderr.flush()
    server = Forkserver()
    config.stash[forkserver_key] = server
    config.add_cleanup(server.close)


class Forkserver:
    def __init__(self) -> None:
        # A private directory keeps other users from connecting to the gateway.
        self.directory = tempfile.TemporaryDirectory(prefix="xdist-fork-")
        self.address = str(Path(self.directory.name) / "workers.sock")
        self.controller_pid = os.getpid()
        self.pid = -1
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(self.address)
            listener.listen()
            self.pid = os.fork()
            if self.pid == 0:
                try:
                    os.setpgid(0, 0)
                    self._serve(listener)
                except BaseException:
                    traceback.print_exc()
                    os._exit(1)
                finally:
                    os._exit(0)
            os.setpgid(self.pid, self.pid)
        except BaseException:
            if self.pid > 0:
                try:
                    os.kill(self.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os.waitpid(self.pid, 0)
            self.directory.cleanup()
            raise
        finally:
            listener.close()

    def _serve(self, listener: socket.socket) -> None:
        listener.settimeout(0.2)
        while os.getppid() == self.controller_pid:
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                pass
            else:
                pid = os.fork()
                if pid == 0:
                    listener.close()
                    try:
                        with open(os.devnull, "r+b") as devnull:
                            os.dup2(devnull.fileno(), 0)
                            os.dup2(devnull.fileno(), 1)
                        io = ForkIO(connection)
                        io.pid = os.getpid()
                        io.write(struct.pack("!Q", os.getpid()))
                        serve(io, id="fork-worker")
                    except BaseException:
                        traceback.print_exc()
                        os._exit(1)
                    finally:
                        os._exit(0)
                connection.close()
            # Workers are children of the server, not of the controller.
            while True:
                try:
                    if os.waitpid(-1, os.WNOHANG)[0] == 0:
                        break
                except ChildProcessError:
                    break
        # Reap the worker group when the controller disappears abruptly.
        os.killpg(os.getpgrp(), signal.SIGTERM)

    def connect(self) -> ForkIO:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(10)
            connection.connect(self.address)
            io = ForkIO(connection)
            io.pid = struct.unpack("!Q", io.read(8))[0]
            connection.settimeout(None)
            return io
        except BaseException:
            connection.close()
            raise

    def close(self) -> None:
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(self.pid, 0)
        finally:
            self.directory.cleanup()


class ForkIO(SocketIO):
    pid: int

    def __init__(self, connection: socket.socket) -> None:
        # SocketIO otherwise tries to set TCP options on the Unix socket.
        self.sock = connection
        self.execmodel = get_execmodel("main_thread_only")

    def kill(self) -> None:
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class ForkserverGroup(execnet.Group):
    def __init__(self, server: Forkserver) -> None:
        super().__init__(execmodel="main_thread_only")
        self.server = server

    def makegateway(self, spec: execnet.XSpec | str | None = None) -> execnet.Gateway:
        if not isinstance(spec, execnet.XSpec):
            spec = execnet.XSpec(spec or self.defaultspec)
        _validate_spec(spec)
        self.allocate_id(spec)
        gateway = execnet.Gateway(self.server.connect(), spec)
        # Keep execnet's normal gateway shutdown and worker restart machinery.
        # This is the remaining seam to replace with an execnet gateway factory.
        self._register(gateway)
        return gateway

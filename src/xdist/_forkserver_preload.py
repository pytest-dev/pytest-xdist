"""Load initial conftests inside multiprocessing's fresh forkserver interpreter."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import traceback

from _pytest.config import _prepareconfig
import pytest

from xdist import _forkserver


def _preload() -> pytest.Config:
    preparation_path = Path(os.environ.pop(_forkserver.PRELOAD_ENV))
    try:
        preparation = json.loads(preparation_path.read_text(encoding="utf-8"))
        os.chdir(preparation["cwd"])
        sys.path[:] = preparation["sys_path"]
        sys.argv[:] = preparation["argv"]
        _forkserver.preloading = True
        config = _prepareconfig(preparation["args"], preparation["plugins"])
        config.hook.pytest_xdist_before_fork(config=config)
        capture = config.pluginmanager.getplugin("capturemanager")
        if capture is not None:
            # Capture files and saved descriptors must be created separately in
            # each child, rather than sharing their offsets across processes.
            capture.stop_global_capturing()
        if threading.active_count() != 1:
            raise pytest.UsageError(
                "forkserver workers require single-threaded imports; stop background "
                "threads in pytest_xdist_before_fork"
            )
        sys.stdout.flush()
        sys.stderr.flush()
        return config
    except BaseException:
        preparation_path.with_name("error.txt").write_text(
            "forkserver could not preload initial conftests:\n"
            + traceback.format_exc(),
            encoding="utf-8",
        )
        raise SystemExit(1) from None
    finally:
        _forkserver.preloading = False


# Retain the unconfigured Config alongside its imported plugins and conftests.
config = _preload()

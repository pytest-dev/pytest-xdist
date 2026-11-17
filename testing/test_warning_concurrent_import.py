from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
from types import SimpleNamespace
import threading
import time
from typing import Any
import warnings

import pytest

from xdist.workermanage import unserialize_warning_message


def test_warning_deserialization_imports_are_serialised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several warning receiver threads must not import warning classes together."""
    imported_name = "_xdist_concurrent_warning_regression"
    original_import = importlib.import_module
    guard = threading.Lock()
    simultaneous = 0
    maximum_simultaneous = 0
    attempts = 0

    def import_module(name: str, package: str | None = None) -> Any:
        nonlocal simultaneous, maximum_simultaneous, attempts
        if name != imported_name:
            return original_import(name, package)
        with guard:
            simultaneous += 1
            attempts += 1
            maximum_simultaneous = max(maximum_simultaneous, simultaneous)
        try:
            # Widen the first-import race without relying on external packages.
            time.sleep(0.03)
            return SimpleNamespace(ConcurrentWarning=UserWarning)
        finally:
            with guard:
                simultaneous -= 1

    monkeypatch.setattr(importlib, "import_module", import_module)

    warning_data: dict[str, Any] = {
        "message_module": imported_name,
        "message_class_name": "ConcurrentWarning",
        "message_args": ("example",),
        "message_str": "example",
        "category_module": None,
    }
    for attribute in warnings.WarningMessage._WARNING_DETAILS:  # type: ignore[attr-defined]
        if attribute == "filename":
            warning_data[attribute] = "test_warning.py"
        elif attribute == "lineno":
            warning_data[attribute] = 1
        else:
            warning_data[attribute] = None

    start = threading.Barrier(8)

    def decode(_: int) -> warnings.WarningMessage:
        start.wait(timeout=5)
        return unserialize_warning_message(warning_data)

    with ThreadPoolExecutor(max_workers=8) as pool:
        decoded = list(pool.map(decode, range(8)))

    assert attempts == 8
    assert maximum_simultaneous == 1
    assert all(isinstance(item.message, UserWarning) for item in decoded)

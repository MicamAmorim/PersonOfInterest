from __future__ import annotations

import atexit
import faulthandler
from pathlib import Path
from typing import IO

from .config import DATA_DIR

_HANDLE: IO[str] | None = None
_INSTALLED = False


def install() -> None:
    global _HANDLE, _INSTALLED
    if _INSTALLED:
        return
    try:
        log_dir = DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path: Path = log_dir / "python-fault.log"
        _HANDLE = path.open("a", encoding="utf-8", buffering=1)
        _HANDLE.write("\n=== PersonOfInterest native fault guard enabled ===\n")
        _HANDLE.flush()
        faulthandler.enable(file=_HANDLE, all_threads=True)
        _INSTALLED = True
    except Exception:
        _HANDLE = None


def _close() -> None:
    global _HANDLE
    if _HANDLE is None:
        return
    try:
        _HANDLE.flush()
        _HANDLE.close()
    except Exception:
        pass
    _HANDLE = None


atexit.register(_close)

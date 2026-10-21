from __future__ import annotations

import sys
import threading
from typing import Any


def install() -> None:
    from .native_fault_guard import install as install_native_fault_guard
    install_native_fault_guard()

    from . import api_v34
    from .session_diagnostics_api import manager, router as diagnostics_router
    from .session_diagnostics_v71_patch import router as diagnostics_v71_router

    if not getattr(api_v34.router, "_poi_session_diagnostics_routes", False):
        api_v34.router.include_router(diagnostics_router)
        api_v34.router._poi_session_diagnostics_routes = True  # type: ignore[attr-defined]
    if not getattr(api_v34.router, "_poi_session_diagnostics_v71_routes", False):
        api_v34.router.include_router(diagnostics_v71_router)
        api_v34.router._poi_session_diagnostics_v71_routes = True  # type: ignore[attr-defined]

    if getattr(threading, "_poi_session_diagnostics_hook", False):
        return

    original_thread_hook = threading.excepthook
    original_sys_hook = sys.excepthook

    def thread_hook(args: Any) -> None:
        try:
            manager.server_error("threading.excepthook", args.exc_type, args.exc_value, args.exc_traceback)
        except Exception:
            pass
        original_thread_hook(args)

    def sys_hook(exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
        try:
            manager.server_error("sys.excepthook", exc_type, exc_value, exc_tb)
        except Exception:
            pass
        original_sys_hook(exc_type, exc_value, exc_tb)

    threading.excepthook = thread_hook
    sys.excepthook = sys_hook
    threading._poi_session_diagnostics_hook = True  # type: ignore[attr-defined]

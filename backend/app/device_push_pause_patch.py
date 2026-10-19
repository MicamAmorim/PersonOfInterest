from __future__ import annotations


def install() -> None:
    from . import api_v34
    from .device_push_pause_api import router as device_push_router

    if getattr(api_v34.router, "_poi_device_push_pause_routes", False):
        return
    api_v34.router.include_router(device_push_router)
    api_v34.router._poi_device_push_pause_routes = True  # type: ignore[attr-defined]

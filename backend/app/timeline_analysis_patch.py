from __future__ import annotations


def install() -> None:
    from . import api_v34
    from .timeline_analysis_api import router as timeline_analysis_router

    if getattr(api_v34.router, "_poi_timeline_analysis_routes", False):
        return
    api_v34.router.include_router(timeline_analysis_router)
    api_v34.router._poi_timeline_analysis_routes = True  # type: ignore[attr-defined]

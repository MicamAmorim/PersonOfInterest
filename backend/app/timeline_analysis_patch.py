from __future__ import annotations


def install() -> None:
    # Install this late, after V5 tracking/manual-integrity have finished wrapping
    # IdentityManager. It closes the race where an in-flight face worker can
    # commit after a human Timeline correction and overwrite the manual label.
    from .manual_identity_persistence_patch import install as install_manual_identity_persistence

    install_manual_identity_persistence()

    from . import api_v34
    from .timeline_analysis_api import router as timeline_analysis_router

    if getattr(api_v34.router, "_poi_timeline_analysis_routes", False):
        return
    api_v34.router.include_router(timeline_analysis_router)
    api_v34.router._poi_timeline_analysis_routes = True  # type: ignore[attr-defined]

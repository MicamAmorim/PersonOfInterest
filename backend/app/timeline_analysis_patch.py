from __future__ import annotations


def install() -> None:
    # Install browser media compatibility before app.main starts syncing cameras.
    # The primary RTSP producer stays untouched for vision/recording; browsers
    # gain a lazy H.264/Opus fallback only when needed.
    from .browser_stream_patch import install as install_browser_stream_patch
    from .browser_media_route_patch import install as install_browser_media_route_patch

    install_browser_stream_patch()
    install_browser_media_route_patch()

    # Install this late, after V5 tracking/manual-integrity have finished wrapping
    # IdentityManager. It closes the race where an in-flight face worker can
    # commit after a human Timeline correction and overwrite the manual label.
    from .manual_identity_persistence_patch import install as install_manual_identity_persistence

    install_manual_identity_persistence()

    # Full-system diagnostics are observational only. Install their API/error
    # hooks from this already-late patch so they can see the final wrapped
    # managers without changing detector/tracker/ReID ownership.
    from .session_diagnostics_patch import install as install_session_diagnostics

    install_session_diagnostics()

    from . import api_v34
    from .timeline_analysis_api import router as timeline_analysis_router

    if getattr(api_v34.router, "_poi_timeline_analysis_routes", False):
        return
    api_v34.router.include_router(timeline_analysis_router)
    api_v34.router._poi_timeline_analysis_routes = True  # type: ignore[attr-defined]

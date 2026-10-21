from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse


def _drop_path(router: Any, path_value: str) -> None:
    router.routes[:] = [route for route in router.routes if getattr(route, "path", None) != path_value]


def install() -> None:
    from .browser_media_compat import browser_compatible_path
    from .storage_recording import recorder_manager
    from . import api_v34, timeline_player_api

    if getattr(api_v34.router, "_poi_browser_media_compat", False):
        return

    path_value = "/api/timeline-player/recordings/{recording_id}"

    def browser_recording_stream(recording_id: int) -> FileResponse:
        source = recorder_manager.recording_path(recording_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Gravação não encontrada")
        compatible = browser_compatible_path(int(recording_id), source)
        headers = {
            "Cache-Control": "private, max-age=3600",
            "X-POI-Media-Compatibility": "h264-cache" if compatible != source else "original",
        }
        return FileResponse(compatible, media_type="video/mp4", headers=headers)

    # storage_recording_patch includes timeline_player_router into api_v34 before
    # this late compatibility patch runs. Replace the copied route in api_v34 as
    # well as the source router so the application cannot keep serving the old
    # HEVC FileResponse by route-order accident.
    _drop_path(timeline_player_api.router, path_value)
    _drop_path(api_v34.router, path_value)

    timeline_player_api.router.add_api_route(
        path_value,
        browser_recording_stream,
        methods=["GET"],
        response_class=FileResponse,
        name="timeline_recording_stream_browser_compatible",
    )
    api_v34.router.add_api_route(
        path_value,
        browser_recording_stream,
        methods=["GET"],
        response_class=FileResponse,
        name="timeline_recording_stream_browser_compatible_v34",
    )
    timeline_player_api.router._poi_browser_media_compat = True  # type: ignore[attr-defined]
    api_v34.router._poi_browser_media_compat = True  # type: ignore[attr-defined]

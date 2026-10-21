from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse


def install() -> None:
    from .browser_media_compat import browser_compatible_path
    from .storage_recording import recorder_manager
    from . import timeline_player_api

    if getattr(timeline_player_api.router, "_poi_browser_media_compat", False):
        return

    path_value = "/api/timeline-player/recordings/{recording_id}"
    kept: list[Any] = []
    for route in timeline_player_api.router.routes:
        if getattr(route, "path", None) == path_value:
            continue
        kept.append(route)
    timeline_player_api.router.routes[:] = kept

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

    timeline_player_api.router.add_api_route(
        path_value,
        browser_recording_stream,
        methods=["GET"],
        response_class=FileResponse,
        name="timeline_recording_stream_browser_compatible",
    )
    timeline_player_api.router._poi_browser_media_compat = True  # type: ignore[attr-defined]

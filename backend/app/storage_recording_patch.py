from __future__ import annotations

from typing import Any

from . import db
from . import false_positive_memory
from . import go2rtc
from . import tracking_v5_patch as tracking
from . import vision
from .storage_recording import RecorderManager, recorder_manager, storage_manager


def install() -> None:
    if getattr(db, "_poi_storage_recording_patch", False):
        return

    # Keep H.264/H.265 video as stream-copy (very low CPU), but transcode only
    # camera audio to AAC. Many inexpensive IP cameras expose PCMA/PCMU, which
    # cannot be muxed into MP4 with a plain `-c copy`.
    if not getattr(RecorderManager, "_poi_mp4_audio_compat", False):
        def compatible_base_command(self: Any, stream_name: str) -> list[str]:
            ffmpeg = self._ffmpeg_executable()
            if not ffmpeg:
                raise RuntimeError("FFmpeg não encontrado. Execute setup novamente ou configure FFMPEG_PATH.")
            return [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "warning",
                "-rtsp_transport",
                "tcp",
                "-i",
                go2rtc.local_restream_url(stream_name),
                "-map",
                "0:v:0?",
                "-map",
                "0:a:0?",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
            ]

        RecorderManager._base_command = compatible_base_command
        RecorderManager._poi_mp4_audio_compat = True

    # main.py imports init_db *after* package patches run. Wrapping it here lets
    # storage/recording initialize after the proven core schema exists without
    # changing detector/tracker/ReID startup ordering.
    original_init_db = db.init_db

    def init_db_with_storage() -> None:
        original_init_db()
        try:
            # Make V5 lifecycle columns available before retention queries inspect
            # identity_origin/best snapshots. This only performs additive schema
            # upgrades already owned by tracking_v5_patch.
            tracking.ensure_schema()
            false_positive_memory.ensure_schema()
            storage_manager.ensure_schema()
            storage_manager.start()
            recorder_manager.start()
        except Exception as exc:
            # Storage/recording are accessory services. A failure here must never
            # prevent PersonOfInterest from starting its cameras or vision motor.
            storage_manager.error = str(exc)
            storage_manager.status_name = "error"

    db.init_db = init_db_with_storage

    # FastAPI already includes api_v34.router. Attach the additive management API
    # to that router before main.py includes it.
    from . import api_v34
    from .storage_recording_api import router as storage_router

    if not getattr(api_v34.router, "_poi_storage_recording_routes", False):
        api_v34.router.include_router(storage_router)
        api_v34.router._poi_storage_recording_routes = True  # type: ignore[attr-defined]

    # main.py always calls vision_manager.stop_all() during shutdown. Extend that
    # final lifecycle step so FFmpeg children are closed gracefully first.
    cls = vision.VisionManager
    if not getattr(cls, "_poi_storage_recording_stop", False):
        original_stop_all = cls.stop_all

        def stop_all_with_recorders(self: Any) -> None:
            try:
                recorder_manager.stop()
            except Exception:
                pass
            try:
                storage_manager.stop()
            except Exception:
                pass
            original_stop_all(self)

        cls.stop_all = stop_all_with_recorders
        cls._poi_storage_recording_stop = True

    db._poi_storage_recording_patch = True

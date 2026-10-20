from __future__ import annotations

import shutil
import time
from typing import Any

from . import db
from . import false_positive_memory
from . import go2rtc
from . import tracking_v5_patch as tracking
from . import vision
from .config import DATA_DIR
from .db import connection
from .storage_recording import (
    RECORDINGS_DIR,
    RecorderManager,
    StorageManager,
    _directory_size,
    recorder_manager,
    storage_manager,
)


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

    # Saving a camera's recording configuration should take effect immediately.
    # Stop only that camera's FFmpeg child after the DB update; the normal
    # reconcile loop restarts it with the new duration/mode if required.
    if not getattr(RecorderManager, "_poi_settings_restart", False):
        original_update_camera_settings = RecorderManager.update_camera_settings

        def update_camera_settings_and_restart(
            self: Any,
            camera_id: int,
            values: dict[str, Any],
        ) -> dict[str, Any]:
            result = original_update_camera_settings(self, camera_id, values)
            try:
                self._stop_session(int(camera_id))
            except Exception:
                pass
            self.notify_change()
            return result

        RecorderManager.update_camera_settings = update_camera_settings_and_restart
        RecorderManager._poi_settings_restart = True

    # If retention cannot reclaim enough space (for example the only file is the
    # segment currently being written), stop recorders instead of allowing NVR
    # video to consume the host's final free bytes. Checks are cached for 5 s so
    # large recording trees are not walked every recorder tick.
    if not getattr(RecorderManager, "_poi_disk_guard", False):
        original_reconcile = RecorderManager._reconcile

        def disk_pressure(self: Any, *, force: bool = False) -> tuple[bool, str]:
            now_mono = time.monotonic()
            cached_at = float(getattr(self, "_poi_disk_guard_checked_at", 0.0) or 0.0)
            if not force and now_mono - cached_at < 5.0:
                return getattr(self, "_poi_disk_guard_result", (False, ""))
            settings = storage_manager.settings()
            try:
                free_bytes = int(shutil.disk_usage(DATA_DIR).free)
            except OSError:
                free_bytes = 0
            recording_bytes = _directory_size(RECORDINGS_DIR)
            reserve_bytes = int(float(settings.get("disk_reserve_gb") or 0) * (1024**3))
            max_bytes = int(float(settings.get("recording_max_gb") or 0) * (1024**3))
            reasons: list[str] = []
            if reserve_bytes > 0 and free_bytes < reserve_bytes:
                reasons.append(
                    f"espaço livre {free_bytes / (1024**3):.2f} GB abaixo da reserva de {reserve_bytes / (1024**3):.2f} GB"
                )
            if max_bytes > 0 and recording_bytes > max_bytes:
                reasons.append(
                    f"gravações {recording_bytes / (1024**3):.2f} GB acima do limite de {max_bytes / (1024**3):.2f} GB"
                )
            result = (bool(reasons), "; ".join(reasons))
            self._poi_disk_guard_checked_at = now_mono
            self._poi_disk_guard_result = result
            return result

        def guarded_reconcile(self: Any) -> None:
            pressured, reason = disk_pressure(self)
            if pressured:
                last_cleanup = float(getattr(self, "_poi_disk_guard_cleanup_at", 0.0) or 0.0)
                if time.monotonic() - last_cleanup >= 30.0:
                    self._poi_disk_guard_cleanup_at = time.monotonic()
                    try:
                        storage_manager.cleanup_now()
                    except Exception:
                        pass
                    self._poi_disk_guard_checked_at = 0.0
                    pressured, reason = disk_pressure(self, force=True)

            if pressured:
                for camera_id in list(self.sessions):
                    self._stop_session(camera_id)
                try:
                    for setting in self.settings():
                        if str(setting.get("mode") or "off") != "off":
                            self.errors[int(setting["camera_id"])] = (
                                "Gravação pausada por proteção de disco: " + reason
                            )
                except Exception:
                    pass
                return

            for camera_id, error in list(self.errors.items()):
                if str(error).startswith("Gravação pausada por proteção de disco:"):
                    self.errors.pop(camera_id, None)
            original_reconcile(self)

        RecorderManager._reconcile = guarded_reconcile
        RecorderManager._poi_disk_guard = True

    # Keep relational residue bounded too. Event cascades remove samples and track
    # observations; this final sweep removes now-empty unknown clusters only.
    if not getattr(StorageManager, "_poi_orphan_cluster_cleanup", False):
        original_delete_events = StorageManager._delete_events

        def delete_events_with_orphan_cleanup(self: Any, ids: list[int]) -> int:
            deleted = original_delete_events(self, ids)
            if deleted:
                try:
                    with connection() as conn:
                        conn.execute(
                            """DELETE FROM unknown_clusters
                            WHERE NOT EXISTS (
                                SELECT 1 FROM face_samples fs
                                WHERE fs.cluster_id = unknown_clusters.id
                            )
                            AND NOT EXISTS (
                                SELECT 1 FROM events e
                                WHERE e.unknown_cluster_id = unknown_clusters.id
                            )"""
                        )
                        conn.commit()
                except Exception:
                    pass
            return deleted

        StorageManager._delete_events = delete_events_with_orphan_cleanup
        StorageManager._poi_orphan_cluster_cleanup = True

    # main.py imports init_db *after* package patches run. Wrapping it here lets
    # storage/recording initialize after the proven core schema exists without
    # changing detector/tracker/ReID startup ordering.
    original_init_db = db.init_db

    def init_db_with_storage() -> None:
        original_init_db()
        try:
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

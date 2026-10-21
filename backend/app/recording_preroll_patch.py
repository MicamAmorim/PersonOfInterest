from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .db import connection, utc_now
from . import storage_recording as sr


BUFFER_ROOT = DATA_DIR / "recording_buffer"
BUFFER_SEGMENT_SECONDS = 2.0
BUFFER_FINALIZE_GRACE_SECONDS = 3.0


@dataclass
class PendingEventClip:
    camera_id: int
    source_event_id: int
    event_at: datetime
    start_at: datetime
    end_at: datetime
    queued_at: float


def _ensure_runtime(self: Any) -> None:
    if not hasattr(self, "_poi_pending_event_clips"):
        self._poi_pending_event_clips: dict[int, PendingEventClip] = {}
    BUFFER_ROOT.mkdir(parents=True, exist_ok=True)


def _is_prebuffer(session: Any) -> bool:
    return bool(getattr(session, "_poi_prebuffer", False))


def _buffer_dir(camera_id: int) -> Path:
    path = BUFFER_ROOT / f"camera_{int(camera_id)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _buffer_segments(camera_id: int) -> list[tuple[datetime, datetime, Path]]:
    directory = _buffer_dir(camera_id)
    raw: list[tuple[float, Path]] = []
    for path in directory.glob("buffer_*.mp4"):
        try:
            if path.stat().st_size <= 0:
                continue
            raw.append((path.stat().st_mtime, path))
        except OSError:
            continue
    raw.sort(key=lambda item: item[0])
    output: list[tuple[datetime, datetime, Path]] = []
    previous_end: float | None = None
    for end_ts, path in raw:
        guessed_start = end_ts - BUFFER_SEGMENT_SECONDS
        if previous_end is not None and 0 < end_ts - previous_end <= 15:
            guessed_start = previous_end
        start = datetime.fromtimestamp(guessed_start, timezone.utc)
        end = datetime.fromtimestamp(end_ts, timezone.utc)
        output.append((start, end, path))
        previous_end = end_ts
    return output


def _start_event_buffer(self: Any, setting: dict[str, Any]) -> None:
    camera_id = int(setting["camera_id"])
    camera = self._camera_row(camera_id)
    if not camera or not camera["enabled"] or camera["sync_status"] != "ok":
        return
    directory = _buffer_dir(camera_id)
    pattern = directory / f"buffer_cam{camera_id}_%Y%m%d_%H%M%S.mp4"
    command = [
        *self._base_command(str(camera["stream_name"])),
        "-f", "segment",
        "-segment_format", "mp4",
        "-segment_time", str(BUFFER_SEGMENT_SECONDS),
        "-reset_timestamps", "1",
        "-strftime", "1",
        str(pattern),
    ]
    log_handle = self._log_handle(camera_id)
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        cwd=str(DATA_DIR),
    )
    session = sr.RecordingSession(
        camera_id=camera_id,
        mode="event",
        process=process,
        log_handle=log_handle,
        started_at=utc_now(),
        started_monotonic=time.monotonic(),
    )
    setattr(session, "_poi_prebuffer", True)
    self.sessions[camera_id] = session
    self.errors.pop(camera_id, None)


def _prune_buffer(self: Any, setting: dict[str, Any]) -> None:
    camera_id = int(setting["camera_id"])
    total_duration = max(
        2.0,
        sr.seconds_for(setting.get("event_duration_value", 60), setting.get("event_duration_unit", "seconds")),
    )
    keep_seconds = max(30.0, total_duration + 30.0)
    cutoff = time.time() - keep_seconds
    pending = getattr(self, "_poi_pending_event_clips", {}).get(camera_id)
    if pending is not None:
        cutoff = min(cutoff, pending.start_at.timestamp() - 10.0)
    for _, end, path in _buffer_segments(camera_id):
        if end.timestamp() >= cutoff:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _queue_event_clip(self: Any, setting: dict[str, Any], event: dict[str, Any]) -> None:
    _ensure_runtime(self)
    camera_id = int(event["camera_id"])
    total_duration = max(
        2.0,
        sr.seconds_for(setting.get("event_duration_value", 60), setting.get("event_duration_unit", "seconds")),
    )
    half = total_duration / 2.0
    event_at = sr._parse_iso(str(event.get("created_at") or "")) or datetime.now(timezone.utc)
    start_at = event_at - timedelta(seconds=half)
    end_at = event_at + timedelta(seconds=half)
    current = self._poi_pending_event_clips.get(camera_id)
    if current is not None and start_at <= current.end_at + timedelta(seconds=BUFFER_SEGMENT_SECONDS * 2):
        current.start_at = min(current.start_at, start_at)
        current.end_at = max(current.end_at, end_at)
        return
    self._poi_pending_event_clips[camera_id] = PendingEventClip(
        camera_id=camera_id,
        source_event_id=int(event["id"]),
        event_at=event_at,
        start_at=start_at,
        end_at=end_at,
        queued_at=time.monotonic(),
    )


def _concat_quote(path: Path) -> str:
    text = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{text}'"


def _finalize_event_clip(self: Any, pending: PendingEventClip) -> bool:
    segments = [
        (start, end, path)
        for start, end, path in _buffer_segments(pending.camera_id)
        if end > pending.start_at and start < pending.end_at
    ]
    if not segments:
        return False
    ffmpeg = self._ffmpeg_executable()
    if not ffmpeg:
        self.errors[pending.camera_id] = "FFmpeg indisponível ao consolidar pré-buffer de evento"
        return False

    directory = self._camera_dir(pending.camera_id)
    stamp = pending.event_at.strftime("%Y%m%d_%H%M%S")
    output = directory / f"event_cam{pending.camera_id}_{stamp}_{pending.source_event_id}.mp4"
    concat_file = _buffer_dir(pending.camera_id) / f"concat_{pending.source_event_id}_{time.time_ns()}.txt"
    try:
        concat_file.write_text("\n".join(_concat_quote(path) for _, _, path in segments) + "\n", encoding="utf-8")
        command = [
            ffmpeg,
            "-hide_banner", "-loglevel", "warning",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output),
        ]
        log_handle = self._log_handle(pending.camera_id)
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                cwd=str(DATA_DIR),
                timeout=120,
                check=False,
            )
        finally:
            try:
                log_handle.close()
            except Exception:
                pass
        if completed.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
            self.errors[pending.camera_id] = f"Falha ao consolidar clipe com pré-buffer (FFmpeg {completed.returncode})"
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
            return False

        actual_start = segments[0][0]
        actual_end = segments[-1][1]
        relative = output.resolve().relative_to(sr.RECORDINGS_DIR.resolve()).as_posix()
        stat = output.stat()
        now = utc_now()
        with connection() as conn:
            conn.execute(
                """INSERT INTO recording_files(
                    camera_id, path, mode, source_event_id, started_at, ended_at,
                    duration_seconds, size_bytes, status, created_at, updated_at
                ) VALUES (?, ?, 'event', ?, ?, ?, ?, ?, 'complete', ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    source_event_id = excluded.source_event_id,
                    started_at = excluded.started_at,
                    ended_at = excluded.ended_at,
                    duration_seconds = excluded.duration_seconds,
                    size_bytes = excluded.size_bytes,
                    status = 'complete', updated_at = excluded.updated_at""",
                (
                    pending.camera_id,
                    relative,
                    pending.source_event_id,
                    actual_start.isoformat(),
                    actual_end.isoformat(),
                    max(0.0, (actual_end - actual_start).total_seconds()),
                    int(stat.st_size),
                    actual_start.isoformat(),
                    now,
                ),
            )
            conn.commit()
        self.errors.pop(pending.camera_id, None)
        return True
    except Exception as exc:
        self.errors[pending.camera_id] = f"Pré-buffer de evento: {exc}"
        return False
    finally:
        try:
            concat_file.unlink(missing_ok=True)
        except OSError:
            pass


def _finalize_due(self: Any) -> None:
    _ensure_runtime(self)
    now = datetime.now(timezone.utc)
    for camera_id, pending in list(self._poi_pending_event_clips.items()):
        if now < pending.end_at + timedelta(seconds=BUFFER_FINALIZE_GRACE_SECONDS):
            continue
        if _finalize_event_clip(self, pending):
            self._poi_pending_event_clips.pop(camera_id, None)
        elif time.monotonic() - pending.queued_at > 60.0:
            self._poi_pending_event_clips.pop(camera_id, None)


def install() -> None:
    cls = sr.RecorderManager
    if getattr(cls, "_poi_event_preroll_v63", False):
        return

    original_init = cls.__init__
    original_status = cls.status

    def init_with_preroll(self: Any) -> None:
        original_init(self)
        _ensure_runtime(self)

    def reconcile_with_preroll(self: Any) -> None:
        _ensure_runtime(self)
        settings = self._settings_by_camera()

        for camera_id, session in list(self.sessions.items()):
            setting = settings.get(camera_id)
            if setting is None or setting["mode"] == "off" or not setting["enabled"] or setting["sync_status"] != "ok":
                self._stop_session(camera_id)
                continue
            if session.process.poll() is not None:
                self.errors[camera_id] = f"FFmpeg encerrou com código {session.process.returncode}"
                self._stop_session(camera_id)
                continue
            if _is_prebuffer(session):
                if setting["mode"] != "event":
                    self._stop_session(camera_id)
                continue
            if session.mode != setting["mode"]:
                self._stop_session(camera_id)

        for camera_id, setting in settings.items():
            if not setting["enabled"] or setting["sync_status"] != "ok":
                continue
            session = self.sessions.get(camera_id)
            if setting["mode"] == "continuous":
                if session is None:
                    try:
                        self._start_continuous(setting)
                    except Exception as exc:
                        self.errors[camera_id] = str(exc)
            elif setting["mode"] == "event":
                if session is None:
                    try:
                        _start_event_buffer(self, setting)
                    except Exception as exc:
                        self.errors[camera_id] = str(exc)
                _prune_buffer(self, setting)

        _finalize_due(self)

        for event in self._new_events():
            camera_id = int(event["camera_id"])
            setting = settings.get(camera_id)
            if setting is None or setting["mode"] != "event":
                continue
            if str(event.get("identity_state") or "") == "false_positive":
                continue
            if not setting["enabled"] or setting["sync_status"] != "ok":
                continue
            _queue_event_clip(self, setting, event)

        _finalize_due(self)

        if time.monotonic() - self._last_index >= 10.0:
            self._last_index = time.monotonic()
            self._index_continuous_files()

    def status_with_preroll(self: Any) -> dict[str, Any]:
        state = original_status(self)
        for item in state.get("sessions", []):
            session = self.sessions.get(int(item.get("camera_id") or 0))
            if session is not None and _is_prebuffer(session):
                item["prebuffer"] = True
                item["deadline_seconds"] = None
        state["pending_event_clips"] = [
            {
                "camera_id": pending.camera_id,
                "source_event_id": pending.source_event_id,
                "start_at": pending.start_at.isoformat(),
                "end_at": pending.end_at.isoformat(),
            }
            for pending in getattr(self, "_poi_pending_event_clips", {}).values()
        ]
        return state

    cls.__init__ = init_with_preroll
    cls._reconcile = reconcile_with_preroll
    cls.status = status_with_preroll
    cls._poi_event_preroll_v63 = True
    _ensure_runtime(sr.recorder_manager)

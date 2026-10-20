from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import go2rtc
from .config import DATA_DIR, DB_PATH, EVENTS_DIR, FACES_DIR, MODELS_DIR
from .db import connection, utc_now

try:
    import imageio_ffmpeg  # type: ignore
except Exception:  # pragma: no cover - optional runtime boundary
    imageio_ffmpeg = None  # type: ignore


RECORDINGS_DIR = DATA_DIR / "recordings"
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False

TIME_UNIT_SECONDS = {
    "seconds": 1.0,
    "minutes": 60.0,
    "hours": 3600.0,
    "days": 86400.0,
    "weeks": 604800.0,
    "months": 2592000.0,
}


def seconds_for(value: float | int, unit: str) -> float:
    key = str(unit or "").strip().lower()
    if key not in TIME_UNIT_SECONDS:
        raise ValueError(f"Unidade de tempo inválida: {unit}")
    return max(0.0, float(value)) * TIME_UNIT_SECONDS[key]


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        with connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS storage_settings (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    cleanup_enabled INTEGER NOT NULL DEFAULT 0,
                    timeline_retention_value REAL NOT NULL DEFAULT 30,
                    timeline_retention_unit TEXT NOT NULL DEFAULT 'days',
                    timeline_max_gb REAL NOT NULL DEFAULT 10,
                    face_auto_limit_per_person INTEGER NOT NULL DEFAULT 30,
                    body_auto_limit_per_person INTEGER NOT NULL DEFAULT 50,
                    protect_manual INTEGER NOT NULL DEFAULT 1,
                    cleanup_interval_minutes REAL NOT NULL DEFAULT 15,
                    false_positive_max_prototypes_per_camera INTEGER NOT NULL DEFAULT 100,
                    false_positive_examples_per_prototype INTEGER NOT NULL DEFAULT 5,
                    recording_retention_value REAL NOT NULL DEFAULT 30,
                    recording_retention_unit TEXT NOT NULL DEFAULT 'days',
                    recording_max_gb REAL NOT NULL DEFAULT 500,
                    disk_reserve_gb REAL NOT NULL DEFAULT 10,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recording_settings (
                    camera_id INTEGER PRIMARY KEY,
                    mode TEXT NOT NULL DEFAULT 'off',
                    event_duration_value REAL NOT NULL DEFAULT 60,
                    event_duration_unit TEXT NOT NULL DEFAULT 'seconds',
                    segment_duration_value REAL NOT NULL DEFAULT 5,
                    segment_duration_unit TEXT NOT NULL DEFAULT 'minutes',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS recording_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id INTEGER NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    mode TEXT NOT NULL,
                    source_event_id INTEGER,
                    started_at TEXT,
                    ended_at TEXT,
                    duration_seconds REAL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'complete',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
                    FOREIGN KEY(source_event_id) REFERENCES events(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_recording_files_camera_started
                    ON recording_files(camera_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_recording_files_status
                    ON recording_files(status, updated_at DESC);
                """
            )
            now = utc_now()
            conn.execute(
                """INSERT OR IGNORE INTO storage_settings(
                    id, cleanup_enabled, timeline_retention_value, timeline_retention_unit,
                    timeline_max_gb, face_auto_limit_per_person, body_auto_limit_per_person,
                    protect_manual, cleanup_interval_minutes,
                    false_positive_max_prototypes_per_camera,
                    false_positive_examples_per_prototype,
                    recording_retention_value, recording_retention_unit,
                    recording_max_gb, disk_reserve_gb, updated_at
                ) VALUES (1, 0, 30, 'days', 10, 30, 50, 1, 15, 100, 5,
                          30, 'days', 500, 10, ?)""",
                (now,),
            )
            conn.execute(
                """INSERT OR IGNORE INTO recording_settings(camera_id, updated_at)
                SELECT id, ? FROM cameras""",
                (now,),
            )
            conn.commit()
        _SCHEMA_READY = True


def _directory_size(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    try:
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def _safe_unlink(root: Path, relative: str | None) -> bool:
    if not relative:
        return False
    try:
        path = (root / relative).resolve()
        resolved_root = root.resolve()
        if resolved_root not in path.parents:
            return False
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except Exception:
        return None


def _as_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _columns(conn: Any, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


class StorageManager:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()
        self.status_name = "stopped"
        self.error: str | None = None
        self.last_cleanup: str | None = None
        self.last_result: dict[str, Any] | None = None

    def ensure_schema(self) -> None:
        ensure_schema()

    def start(self) -> None:
        self.ensure_schema()
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.wake_event.clear()
            self.thread = threading.Thread(target=self._run, name="poi-storage", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)

    def notify_change(self) -> None:
        self.wake_event.set()

    def settings(self) -> dict[str, Any]:
        self.ensure_schema()
        with connection() as conn:
            row = conn.execute("SELECT * FROM storage_settings WHERE id = 1").fetchone()
        data = dict(row) if row else {}
        for key in ("cleanup_enabled", "protect_manual"):
            if key in data:
                data[key] = bool(data[key])
        return data

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        allowed = {
            "cleanup_enabled",
            "timeline_retention_value",
            "timeline_retention_unit",
            "timeline_max_gb",
            "face_auto_limit_per_person",
            "body_auto_limit_per_person",
            "protect_manual",
            "cleanup_interval_minutes",
            "false_positive_max_prototypes_per_camera",
            "false_positive_examples_per_prototype",
            "recording_retention_value",
            "recording_retention_unit",
            "recording_max_gb",
            "disk_reserve_gb",
        }
        clean: dict[str, Any] = {}
        for key, value in values.items():
            if key not in allowed:
                continue
            if key in {"cleanup_enabled", "protect_manual"}:
                clean[key] = int(bool(value))
            elif key.endswith("_unit"):
                unit = str(value).strip().lower()
                if unit not in TIME_UNIT_SECONDS:
                    raise ValueError(f"Unidade inválida em {key}")
                clean[key] = unit
            elif key in {
                "face_auto_limit_per_person",
                "body_auto_limit_per_person",
                "false_positive_max_prototypes_per_camera",
                "false_positive_examples_per_prototype",
            }:
                clean[key] = max(1, min(10000, int(value)))
            else:
                number = float(value)
                if number < 0:
                    raise ValueError(f"{key} não pode ser negativo")
                clean[key] = number
        if not clean:
            return self.settings()
        assignments = ", ".join(f"{key} = ?" for key in clean)
        with connection() as conn:
            conn.execute(
                f"UPDATE storage_settings SET {assignments}, updated_at = ? WHERE id = 1",
                [*clean.values(), utc_now()],
            )
            conn.commit()
        self.notify_change()
        return self.settings()

    def _event_paths_and_crops(self, ids: list[int]) -> tuple[list[tuple[str, str]], list[int]]:
        if not ids:
            return [], []
        marks = ",".join("?" for _ in ids)
        files: list[tuple[str, str]] = []
        found: list[int] = []
        with connection() as conn:
            columns = _columns(conn, "events")
            path_columns = [name for name in ("snapshot_path", "trigger_snapshot_path", "best_snapshot_path") if name in columns]
            select_paths = ", ".join(path_columns) if path_columns else "NULL AS snapshot_path"
            rows = conn.execute(
                f"SELECT id, {select_paths} FROM events WHERE id IN ({marks})",
                ids,
            ).fetchall()
            for row in rows:
                found.append(int(row["id"]))
                for name in path_columns:
                    relative = row[name]
                    if relative:
                        files.append(("events", str(relative)))
            face_rows = conn.execute(
                f"SELECT crop_path FROM face_samples WHERE event_id IN ({marks}) AND crop_path IS NOT NULL",
                ids,
            ).fetchall()
            files.extend(("faces", str(row["crop_path"])) for row in face_rows if row["crop_path"])
        return files, found

    def _delete_events(self, ids: list[int]) -> int:
        files, found = self._event_paths_and_crops(ids)
        if not found:
            return 0
        marks = ",".join("?" for _ in found)
        with connection() as conn:
            conn.execute(f"DELETE FROM events WHERE id IN ({marks})", found)
            conn.commit()
        seen: set[tuple[str, str]] = set()
        for root_name, relative in files:
            key = (root_name, relative)
            if key in seen:
                continue
            seen.add(key)
            _safe_unlink(EVENTS_DIR if root_name == "events" else FACES_DIR, relative)
        return len(found)

    def _manual_event_clause(self, protect_manual: bool) -> str:
        if not protect_manual:
            return "1=1"
        return """COALESCE(e.identity_origin, 'vision') NOT LIKE 'manual%'
            AND NOT EXISTS (
                SELECT 1 FROM body_samples bs
                WHERE bs.event_id = e.id AND bs.source LIKE '%manual%'
            )"""

    def _cleanup_timeline_by_age(self, settings: dict[str, Any]) -> int:
        if not settings.get("cleanup_enabled"):
            return 0
        retention_seconds = seconds_for(
            settings.get("timeline_retention_value", 30),
            settings.get("timeline_retention_unit", "days"),
        )
        if retention_seconds <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=retention_seconds)
        with connection() as conn:
            rows = conn.execute(
                f"""SELECT e.id FROM events e
                WHERE e.created_at < ? AND {self._manual_event_clause(bool(settings.get('protect_manual')))}
                ORDER BY e.created_at ASC LIMIT 2000""",
                (cutoff.isoformat(),),
            ).fetchall()
        return self._delete_events([int(row["id"]) for row in rows])

    def _timeline_bytes(self) -> int:
        return _directory_size(EVENTS_DIR) + _directory_size(FACES_DIR)

    def _cleanup_timeline_by_size(self, settings: dict[str, Any]) -> int:
        if not settings.get("cleanup_enabled"):
            return 0
        max_bytes = int(float(settings.get("timeline_max_gb") or 0) * (1024**3))
        if max_bytes <= 0:
            return 0
        removed = 0
        loops = 0
        while self._timeline_bytes() > max_bytes and loops < 50:
            loops += 1
            with connection() as conn:
                rows = conn.execute(
                    f"""SELECT e.id FROM events e
                    WHERE {self._manual_event_clause(bool(settings.get('protect_manual')))}
                    ORDER BY e.created_at ASC LIMIT 100"""
                ).fetchall()
            if not rows:
                break
            removed += self._delete_events([int(row["id"]) for row in rows])
        return removed

    def _prune_face_samples(self, settings: dict[str, Any]) -> int:
        limit = max(1, int(settings.get("face_auto_limit_per_person") or 30))
        protect_manual = bool(settings.get("protect_manual"))
        with connection() as conn:
            persons = [int(row[0]) for row in conn.execute("SELECT id FROM persons").fetchall()]
        removed = 0
        for person_id in persons:
            with connection() as conn:
                columns = _columns(conn, "face_samples")
                active_expr = "COALESCE(fs.active, 1)" if "active" in columns else "1"
                rows = conn.execute(
                    f"""SELECT fs.id, fs.crop_path, fs.quality, fs.created_at,
                        COALESCE(e.identity_origin, 'vision') AS identity_origin
                    FROM face_samples fs
                    LEFT JOIN events e ON e.id = fs.event_id
                    WHERE fs.person_id = ? AND {active_expr} = 1
                    ORDER BY fs.quality DESC, fs.created_at DESC""",
                    (person_id,),
                ).fetchall()
                automatic = [
                    row for row in rows
                    if not (protect_manual and str(row["identity_origin"] or "").startswith("manual"))
                ]
                extras = automatic[limit:]
                if extras:
                    ids = [int(row["id"]) for row in extras]
                    marks = ",".join("?" for _ in ids)
                    conn.execute(f"DELETE FROM face_samples WHERE id IN ({marks})", ids)
                    conn.commit()
            for row in extras:
                if row["crop_path"]:
                    _safe_unlink(FACES_DIR, str(row["crop_path"]))
            removed += len(extras)
        return removed

    def _prune_body_samples(self, settings: dict[str, Any]) -> int:
        limit = max(1, int(settings.get("body_auto_limit_per_person") or 50))
        protect_manual = bool(settings.get("protect_manual"))
        with connection() as conn:
            persons = [int(row[0]) for row in conn.execute("SELECT id FROM persons").fetchall()]
        removed = 0
        for person_id in persons:
            with connection() as conn:
                columns = _columns(conn, "body_samples")
                active_expr = "COALESCE(active, 1)" if "active" in columns else "1"
                rows = conn.execute(
                    f"""SELECT id, quality, source, created_at FROM body_samples
                    WHERE person_id = ? AND verified = 1 AND {active_expr} = 1
                    ORDER BY quality DESC, created_at DESC""",
                    (person_id,),
                ).fetchall()
                automatic = [
                    row for row in rows
                    if not (protect_manual and "manual" in str(row["source"] or "").lower())
                ]
                extras = automatic[limit:]
                if extras:
                    ids = [int(row["id"]) for row in extras]
                    marks = ",".join("?" for _ in ids)
                    conn.execute(f"DELETE FROM body_samples WHERE id IN ({marks})", ids)
                    conn.commit()
            removed += len(extras)
        return removed

    def _recording_candidates(self) -> list[Path]:
        if not RECORDINGS_DIR.exists():
            return []
        now = time.time()
        items: list[tuple[float, Path]] = []
        for path in RECORDINGS_DIR.rglob("*.mp4"):
            try:
                stat = path.stat()
            except OSError:
                continue
            # Never delete a file that may still be actively written.
            if now - stat.st_mtime < 120:
                continue
            items.append((stat.st_mtime, path))
        items.sort(key=lambda item: item[0])
        return [path for _, path in items]

    def _delete_recording_file(self, path: Path) -> int:
        try:
            resolved = path.resolve()
            if RECORDINGS_DIR.resolve() not in resolved.parents:
                return 0
            size = resolved.stat().st_size if resolved.exists() else 0
            relative = resolved.relative_to(RECORDINGS_DIR.resolve()).as_posix()
            resolved.unlink(missing_ok=True)
            with connection() as conn:
                conn.execute("DELETE FROM recording_files WHERE path = ?", (relative,))
                conn.commit()
            return int(size)
        except OSError:
            return 0

    def _cleanup_recordings(self, settings: dict[str, Any]) -> tuple[int, int]:
        removed_files = 0
        removed_bytes = 0
        retention_seconds = seconds_for(
            settings.get("recording_retention_value", 30),
            settings.get("recording_retention_unit", "days"),
        )
        cutoff = time.time() - retention_seconds if retention_seconds > 0 else None
        candidates = self._recording_candidates()
        if cutoff is not None:
            for path in list(candidates):
                try:
                    if path.stat().st_mtime < cutoff:
                        removed_bytes += self._delete_recording_file(path)
                        removed_files += 1
                except OSError:
                    continue
        max_bytes = int(float(settings.get("recording_max_gb") or 0) * (1024**3))
        reserve_bytes = int(float(settings.get("disk_reserve_gb") or 0) * (1024**3))
        loops = 0
        while loops < 10000:
            loops += 1
            current = _directory_size(RECORDINGS_DIR)
            try:
                free = shutil.disk_usage(DATA_DIR).free
            except OSError:
                free = reserve_bytes
            over_max = max_bytes > 0 and current > max_bytes
            below_reserve = reserve_bytes > 0 and free < reserve_bytes
            if not over_max and not below_reserve:
                break
            candidates = self._recording_candidates()
            if not candidates:
                break
            removed_bytes += self._delete_recording_file(candidates[0])
            removed_files += 1
        return removed_files, removed_bytes

    def cleanup_now(self) -> dict[str, Any]:
        self.ensure_schema()
        settings = self.settings()
        result = {
            "timeline_removed_by_age": 0,
            "timeline_removed_by_size": 0,
            "face_samples_removed": 0,
            "body_samples_removed": 0,
            "recording_files_removed": 0,
            "recording_bytes_removed": 0,
        }
        try:
            result["timeline_removed_by_age"] = self._cleanup_timeline_by_age(settings)
            result["timeline_removed_by_size"] = self._cleanup_timeline_by_size(settings)
            if settings.get("cleanup_enabled"):
                result["face_samples_removed"] = self._prune_face_samples(settings)
                result["body_samples_removed"] = self._prune_body_samples(settings)
            files, bytes_removed = self._cleanup_recordings(settings)
            result["recording_files_removed"] = files
            result["recording_bytes_removed"] = bytes_removed
            self.status_name = "running"
            self.error = None
        except Exception as exc:
            self.status_name = "error"
            self.error = str(exc)
            result["error"] = str(exc)
        self.last_cleanup = utc_now()
        self.last_result = result
        return result

    def status(self) -> dict[str, Any]:
        self.ensure_schema()
        try:
            usage = shutil.disk_usage(DATA_DIR)
            disk_total = int(usage.total)
            disk_free = int(usage.free)
        except OSError:
            disk_total = disk_free = 0
        with connection() as conn:
            counts = {
                "events": int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
                "face_samples": int(conn.execute("SELECT COUNT(*) FROM face_samples").fetchone()[0]),
                "body_samples": int(conn.execute("SELECT COUNT(*) FROM body_samples").fetchone()[0]),
            }
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='false_positive_prototypes'"
            ).fetchone():
                counts["false_positive_prototypes"] = int(
                    conn.execute("SELECT COUNT(*) FROM false_positive_prototypes WHERE active = 1").fetchone()[0]
                )
            else:
                counts["false_positive_prototypes"] = 0
        return {
            "status": self.status_name,
            "error": self.error,
            "last_cleanup": self.last_cleanup,
            "last_result": self.last_result,
            "bytes": {
                "timeline": self._timeline_bytes(),
                "events": _directory_size(EVENTS_DIR),
                "faces": _directory_size(FACES_DIR),
                "recordings": _directory_size(RECORDINGS_DIR),
                "models": _directory_size(MODELS_DIR),
                "database": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
                "disk_total": disk_total,
                "disk_free": disk_free,
            },
            "counts": counts,
            "settings": self.settings(),
        }

    def _run(self) -> None:  # pragma: no cover - background integration
        self.status_name = "running"
        while not self.stop_event.is_set():
            try:
                settings = self.settings()
                self.cleanup_now()
                interval = max(1.0, float(settings.get("cleanup_interval_minutes") or 15)) * 60.0
            except Exception as exc:
                self.status_name = "error"
                self.error = str(exc)
                interval = 60.0
            self.wake_event.wait(interval)
            self.wake_event.clear()


@dataclass
class RecordingSession:
    camera_id: int
    mode: str
    process: subprocess.Popen[Any]
    log_handle: Any
    started_at: str
    started_monotonic: float
    explicit_path: Path | None = None
    deadline_monotonic: float | None = None
    source_event_id: int | None = None


class RecorderManager:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()
        self.sessions: dict[int, RecordingSession] = {}
        self.errors: dict[int, str] = {}
        self._event_cursor = 0
        self._last_index = 0.0
        self._ffmpeg: str | None = None

    def ensure_schema(self) -> None:
        ensure_schema()
        now = utc_now()
        with connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO recording_settings(camera_id, updated_at)
                SELECT id, ? FROM cameras""",
                (now,),
            )
            conn.commit()

    def _ffmpeg_executable(self) -> str | None:
        if self._ffmpeg:
            return self._ffmpeg
        explicit = os.getenv("FFMPEG_PATH", "").strip()
        if explicit and Path(explicit).is_file():
            self._ffmpeg = explicit
            return explicit
        system = shutil.which("ffmpeg")
        if system:
            self._ffmpeg = system
            return system
        if imageio_ffmpeg is not None:
            try:
                candidate = str(imageio_ffmpeg.get_ffmpeg_exe())
                if Path(candidate).is_file():
                    self._ffmpeg = candidate
                    return candidate
            except Exception:
                pass
        return None

    def start(self) -> None:
        self.ensure_schema()
        with connection() as conn:
            row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()
            self._event_cursor = int(row[0] if row else 0)
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.wake_event.clear()
            self.thread = threading.Thread(target=self._run, name="poi-recorder", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=4.0)
        with self.lock:
            for camera_id in list(self.sessions):
                self._stop_session(camera_id)

    def notify_change(self) -> None:
        self.wake_event.set()

    def settings(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with connection() as conn:
            rows = conn.execute(
                """SELECT rs.*, c.name AS camera_name, c.enabled, c.sync_status
                FROM recording_settings rs
                JOIN cameras c ON c.id = rs.camera_id
                ORDER BY c.name COLLATE NOCASE"""
            ).fetchall()
        return [
            {
                **dict(row),
                "enabled": bool(row["enabled"]),
            }
            for row in rows
        ]

    def update_camera_settings(self, camera_id: int, values: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        with connection() as conn:
            camera = conn.execute("SELECT id FROM cameras WHERE id = ?", (int(camera_id),)).fetchone()
            if camera is None:
                raise LookupError("Câmera não encontrada")
            conn.execute(
                "INSERT OR IGNORE INTO recording_settings(camera_id, updated_at) VALUES (?, ?)",
                (int(camera_id), utc_now()),
            )
            conn.commit()
        allowed = {
            "mode",
            "event_duration_value",
            "event_duration_unit",
            "segment_duration_value",
            "segment_duration_unit",
        }
        clean: dict[str, Any] = {}
        for key, value in values.items():
            if key not in allowed:
                continue
            if key == "mode":
                mode = str(value).strip().lower()
                if mode not in {"off", "continuous", "event"}:
                    raise ValueError("Modo de gravação inválido")
                clean[key] = mode
            elif key.endswith("_unit"):
                unit = str(value).strip().lower()
                if unit not in TIME_UNIT_SECONDS:
                    raise ValueError(f"Unidade inválida em {key}")
                clean[key] = unit
            else:
                number = float(value)
                if number <= 0:
                    raise ValueError(f"{key} deve ser maior que zero")
                clean[key] = number
        if clean:
            assignments = ", ".join(f"{key} = ?" for key in clean)
            with connection() as conn:
                conn.execute(
                    f"UPDATE recording_settings SET {assignments}, updated_at = ? WHERE camera_id = ?",
                    [*clean.values(), utc_now(), int(camera_id)],
                )
                conn.commit()
        self.notify_change()
        return next(item for item in self.settings() if int(item["camera_id"]) == int(camera_id))

    def _camera_row(self, camera_id: int) -> dict[str, Any] | None:
        with connection() as conn:
            row = conn.execute(
                "SELECT id, name, stream_name, enabled, sync_status FROM cameras WHERE id = ?",
                (int(camera_id),),
            ).fetchone()
        return dict(row) if row else None

    def _camera_dir(self, camera_id: int) -> Path:
        now = datetime.now(timezone.utc)
        path = RECORDINGS_DIR / f"camera_{int(camera_id)}" / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _log_handle(self, camera_id: int) -> Any:
        log_dir = DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return (log_dir / f"recorder-camera-{int(camera_id)}.log").open("a", encoding="utf-8")

    def _base_command(self, stream_name: str) -> list[str]:
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
            "0:v?",
            "-map",
            "0:a?",
            "-c",
            "copy",
        ]

    def _start_continuous(self, setting: dict[str, Any]) -> None:
        camera_id = int(setting["camera_id"])
        camera = self._camera_row(camera_id)
        if not camera or not camera["enabled"] or camera["sync_status"] != "ok":
            return
        segment_seconds = max(10.0, seconds_for(setting["segment_duration_value"], setting["segment_duration_unit"]))
        directory = self._camera_dir(camera_id)
        pattern = directory / f"continuous_cam{camera_id}_%Y%m%d_%H%M%S.mp4"
        command = [
            *self._base_command(str(camera["stream_name"])),
            "-f",
            "segment",
            "-segment_format",
            "mp4",
            "-segment_time",
            str(segment_seconds),
            "-reset_timestamps",
            "1",
            "-strftime",
            "1",
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
        self.sessions[camera_id] = RecordingSession(
            camera_id=camera_id,
            mode="continuous",
            process=process,
            log_handle=log_handle,
            started_at=utc_now(),
            started_monotonic=time.monotonic(),
        )
        self.errors.pop(camera_id, None)

    def _start_event(self, setting: dict[str, Any], event_id: int) -> None:
        camera_id = int(setting["camera_id"])
        camera = self._camera_row(camera_id)
        if not camera or not camera["enabled"] or camera["sync_status"] != "ok":
            return
        duration = max(1.0, seconds_for(setting["event_duration_value"], setting["event_duration_unit"]))
        directory = self._camera_dir(camera_id)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = directory / f"event_cam{camera_id}_{stamp}_{int(event_id)}.mp4"
        command = [*self._base_command(str(camera["stream_name"])), "-movflags", "+faststart", str(path)]
        log_handle = self._log_handle(camera_id)
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(DATA_DIR),
        )
        self.sessions[camera_id] = RecordingSession(
            camera_id=camera_id,
            mode="event",
            process=process,
            log_handle=log_handle,
            started_at=utc_now(),
            started_monotonic=time.monotonic(),
            explicit_path=path,
            deadline_monotonic=time.monotonic() + duration,
            source_event_id=int(event_id),
        )
        self.errors.pop(camera_id, None)

    def _graceful_stop(self, process: subprocess.Popen[Any]) -> None:
        if process.poll() is not None:
            return
        try:
            if process.stdin:
                process.stdin.write(b"q\n")
                process.stdin.flush()
            process.wait(timeout=8)
            return
        except Exception:
            pass
        try:
            process.terminate()
            process.wait(timeout=4)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _index_event_file(self, session: RecordingSession) -> None:
        path = session.explicit_path
        if path is None or not path.is_file():
            return
        try:
            relative = path.resolve().relative_to(RECORDINGS_DIR.resolve()).as_posix()
            stat = path.stat()
        except (OSError, ValueError):
            return
        ended = utc_now()
        duration = max(0.0, time.monotonic() - session.started_monotonic)
        with connection() as conn:
            conn.execute(
                """INSERT INTO recording_files(
                    camera_id, path, mode, source_event_id, started_at, ended_at,
                    duration_seconds, size_bytes, status, created_at, updated_at
                ) VALUES (?, ?, 'event', ?, ?, ?, ?, ?, 'complete', ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    ended_at = excluded.ended_at,
                    duration_seconds = excluded.duration_seconds,
                    size_bytes = excluded.size_bytes,
                    status = 'complete', updated_at = excluded.updated_at""",
                (
                    session.camera_id,
                    relative,
                    session.source_event_id,
                    session.started_at,
                    ended,
                    duration,
                    int(stat.st_size),
                    session.started_at,
                    ended,
                ),
            )
            conn.commit()

    def _stop_session(self, camera_id: int) -> None:
        session = self.sessions.pop(int(camera_id), None)
        if session is None:
            return
        self._graceful_stop(session.process)
        try:
            session.log_handle.close()
        except Exception:
            pass
        if session.mode == "event":
            self._index_event_file(session)

    def _index_continuous_files(self) -> None:
        if not RECORDINGS_DIR.exists():
            return
        now = utc_now()
        for path in RECORDINGS_DIR.rglob("continuous_cam*.mp4"):
            try:
                resolved = path.resolve()
                relative = resolved.relative_to(RECORDINGS_DIR.resolve()).as_posix()
                stat = resolved.stat()
                parts = relative.split("/")
                camera_part = next((part for part in parts if part.startswith("camera_")), "")
                camera_id = int(camera_part.split("_", 1)[1])
            except (OSError, ValueError, IndexError):
                continue
            started = _as_iso(stat.st_mtime)
            with connection() as conn:
                conn.execute(
                    """INSERT INTO recording_files(
                        camera_id, path, mode, started_at, ended_at, size_bytes,
                        status, created_at, updated_at
                    ) VALUES (?, ?, 'continuous', ?, ?, ?, 'complete', ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        ended_at = excluded.ended_at,
                        size_bytes = excluded.size_bytes,
                        updated_at = excluded.updated_at""",
                    (camera_id, relative, started, started, int(stat.st_size), started, now),
                )
                conn.commit()

    def _new_events(self) -> list[dict[str, Any]]:
        with connection() as conn:
            rows = conn.execute(
                """SELECT id, camera_id, identity_state, created_at
                FROM events WHERE id > ? ORDER BY id ASC LIMIT 500""",
                (self._event_cursor,),
            ).fetchall()
        if rows:
            self._event_cursor = max(self._event_cursor, max(int(row["id"]) for row in rows))
        return [dict(row) for row in rows]

    def _settings_by_camera(self) -> dict[int, dict[str, Any]]:
        return {int(item["camera_id"]): item for item in self.settings()}

    def _reconcile(self) -> None:
        settings = self._settings_by_camera()
        for camera_id, session in list(self.sessions.items()):
            setting = settings.get(camera_id)
            if setting is None or setting["mode"] == "off" or not setting["enabled"] or setting["sync_status"] != "ok":
                self._stop_session(camera_id)
                continue
            if session.process.poll() is not None:
                code = session.process.returncode
                self.errors[camera_id] = f"FFmpeg encerrou com código {code}"
                self._stop_session(camera_id)
                continue
            if session.mode != setting["mode"]:
                self._stop_session(camera_id)
                continue
            if session.mode == "event" and session.deadline_monotonic is not None and time.monotonic() >= session.deadline_monotonic:
                self._stop_session(camera_id)

        for camera_id, setting in settings.items():
            if setting["mode"] != "continuous" or camera_id in self.sessions:
                continue
            if not setting["enabled"] or setting["sync_status"] != "ok":
                continue
            try:
                self._start_continuous(setting)
            except Exception as exc:
                self.errors[camera_id] = str(exc)

        for event in self._new_events():
            camera_id = int(event["camera_id"])
            setting = settings.get(camera_id)
            if setting is None or setting["mode"] != "event":
                continue
            if str(event.get("identity_state") or "") == "false_positive":
                continue
            if not setting["enabled"] or setting["sync_status"] != "ok":
                continue
            duration = max(1.0, seconds_for(setting["event_duration_value"], setting["event_duration_unit"]))
            session = self.sessions.get(camera_id)
            if session and session.mode == "event" and session.process.poll() is None:
                session.deadline_monotonic = max(
                    float(session.deadline_monotonic or 0.0),
                    time.monotonic() + duration,
                )
                continue
            try:
                self._start_event(setting, int(event["id"]))
            except Exception as exc:
                self.errors[camera_id] = str(exc)

        if time.monotonic() - self._last_index >= 10.0:
            self._last_index = time.monotonic()
            self._index_continuous_files()

    def _run(self) -> None:  # pragma: no cover - background integration
        while not self.stop_event.is_set():
            try:
                self._reconcile()
            except Exception:
                pass
            self.wake_event.wait(1.0)
            self.wake_event.clear()

    def status(self) -> dict[str, Any]:
        ffmpeg = self._ffmpeg_executable()
        sessions: list[dict[str, Any]] = []
        with self.lock:
            for camera_id, session in self.sessions.items():
                sessions.append(
                    {
                        "camera_id": camera_id,
                        "mode": session.mode,
                        "started_at": session.started_at,
                        "source_event_id": session.source_event_id,
                        "deadline_seconds": max(0.0, (session.deadline_monotonic or time.monotonic()) - time.monotonic())
                        if session.mode == "event" else None,
                        "running": session.process.poll() is None,
                    }
                )
        return {
            "ffmpeg_available": bool(ffmpeg),
            "ffmpeg_path": ffmpeg,
            "sessions": sessions,
            "errors": {str(key): value for key, value in self.errors.items()},
        }

    def list_recordings(self, *, camera_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
        self.ensure_schema()
        sql = """SELECT rf.*, c.name AS camera_name FROM recording_files rf
            JOIN cameras c ON c.id = rf.camera_id"""
        params: list[Any] = []
        if camera_id is not None:
            sql += " WHERE rf.camera_id = ?"
            params.append(int(camera_id))
        sql += " ORDER BY COALESCE(rf.started_at, rf.created_at) DESC LIMIT ?"
        params.append(max(1, min(1000, int(limit))))
        with connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                **dict(row),
                "file_url": f"/api/recordings/{int(row['id'])}/file",
            }
            for row in rows
        ]

    def recording_path(self, recording_id: int) -> Path | None:
        self.ensure_schema()
        with connection() as conn:
            row = conn.execute("SELECT path FROM recording_files WHERE id = ?", (int(recording_id),)).fetchone()
        if row is None:
            return None
        path = (RECORDINGS_DIR / str(row["path"])).resolve()
        if RECORDINGS_DIR.resolve() not in path.parents or not path.is_file():
            return None
        return path


storage_manager = StorageManager()
recorder_manager = RecorderManager()

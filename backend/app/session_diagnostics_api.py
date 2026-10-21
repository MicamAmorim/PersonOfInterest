from __future__ import annotations

import ctypes
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .config import APP_NAME, APP_VERSION, DATA_DIR, DB_PATH, PROJECT_ROOT
from .db import connection, utc_now

router = APIRouter(prefix="/api/diagnostics/session", tags=["diagnostics"])
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
MAX_EVENT_BODY = 2 * 1024 * 1024
MAX_SCREEN_BYTES = 250 * 1024 * 1024
ALLOWED_CATEGORIES = {
    "frontend-actions",
    "frontend-state",
    "performance",
    "media",
    "api",
    "errors",
    "markers",
    "system",
    "component-state",
    "backend-errors",
}
_SECRET_KEYS = ("password", "passwd", "secret", "token", "authorization", "credential", "embedding", "vapid", "rtsp")
_URL_CREDENTIALS = re.compile(r"(?i)(rtsp://)([^/@\s]+)@")
_MODULE_STARTED = time.monotonic()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    return repr(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "<max-depth>"
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if any(secret in lowered for secret in _SECRET_KEYS):
                clean[key] = "<redacted>"
            else:
                clean[key] = _sanitize(raw_value, depth + 1)
        return clean
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item, depth + 1) for item in list(value)[:500]]
    if isinstance(value, str):
        text = _URL_CREDENTIALS.sub(r"\1***:***@", value)
        return text if len(text) <= 2000 else text[:2000] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _sanitize(_json_default(value), depth + 1)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_sanitize(payload), ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(_sanitize(payload), ensure_ascii=False, separators=(",", ":"), default=_json_default)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _git_info() -> dict[str, Any]:
    result: dict[str, Any] = {"commit": None, "dirty": None}
    try:
        result["commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT), text=True, timeout=2,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=str(PROJECT_ROOT), text=True, timeout=2,
            stderr=subprocess.DEVNULL,
        ).splitlines()
        result["dirty"] = bool(status)
        result["changed_paths"] = [line[3:] for line in status[:100] if len(line) > 3]
    except Exception:
        pass
    return result


def _runtime_info() -> dict[str, Any]:
    versions: dict[str, str | None] = {}
    for name in ("cv2", "numpy", "onnxruntime", "fastapi", "uvicorn"):
        try:
            module = __import__(name)
            versions[name] = str(getattr(module, "__version__", "unknown"))
        except Exception:
            versions[name] = None
    return {
        "app": APP_NAME,
        "app_version": APP_VERSION,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "pid": os.getpid(),
        "versions": versions,
        "opencl_disabled": os.getenv("POI_DISABLE_OPENCL", "1").strip().lower() not in {"0", "false", "no", "off"},
        "git": _git_info(),
    }


def _process_memory_bytes() -> int | None:
    try:
        if os.name == "nt":
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            return int(counters.WorkingSetSize) if ok else None
        import resource  # type: ignore
        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return rss if sys.platform == "darwin" else rss * 1024
    except Exception:
        return None


def _table_exists(conn: Any, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _columns(conn: Any, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _count(conn: Any, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _db_summary(meta: dict[str, Any]) -> dict[str, Any]:
    started = str(meta.get("started_at") or "")
    ended = str(meta.get("ended_at") or _now_iso())
    include_tonho_text = bool(meta.get("include_tonho_text"))
    result: dict[str, Any] = {"range": {"started_at": started, "ended_at": ended}, "counts": {}, "invariants": {}, "session_rows": {}}
    try:
        with connection() as conn:
            for table in (
                "cameras", "persons", "events", "track_observations", "face_samples", "body_samples",
                "recording_files", "assistant_wake_log", "false_positive_prototypes", "push_subscriptions",
            ):
                result["counts"][table] = _count(conn, table)

            event_cols = _columns(conn, "events")
            wanted = [
                "id", "camera_id", "track_id", "person_id", "probable_person_id", "identity_state",
                "identity_origin", "track_status", "observation_count", "best_frame_quality",
                "best_face_quality", "best_body_quality", "created_at", "last_seen_at", "ended_at",
            ]
            select = [item for item in wanted if item in event_cols]
            if select and "created_at" in event_cols:
                rows = conn.execute(
                    f"SELECT {', '.join(select)} FROM events WHERE created_at >= ? AND created_at <= ? ORDER BY created_at LIMIT 5000",
                    (started, ended),
                ).fetchall()
                result["session_rows"]["events"] = [dict(row) for row in rows]

            rec_cols = _columns(conn, "recording_files")
            rec_wanted = ["id", "camera_id", "mode", "source_event_id", "started_at", "ended_at", "duration_seconds", "size_bytes", "status"]
            rec_select = [item for item in rec_wanted if item in rec_cols]
            if rec_select and "started_at" in rec_cols:
                rows = conn.execute(
                    f"SELECT {', '.join(rec_select)} FROM recording_files WHERE started_at >= ? AND started_at <= ? ORDER BY started_at LIMIT 2000",
                    (started, ended),
                ).fetchall()
                result["session_rows"]["recordings"] = [dict(row) for row in rows]

            wake_cols = _columns(conn, "assistant_wake_log")
            wake_wanted = ["id", "camera_id", "matched", "certainty", "person_id", "created_at"]
            if include_tonho_text:
                wake_wanted += ["transcript", "response_text"]
            wake_select = [item for item in wake_wanted if item in wake_cols]
            if wake_select and "created_at" in wake_cols:
                rows = conn.execute(
                    f"SELECT {', '.join(wake_select)} FROM assistant_wake_log WHERE created_at >= ? AND created_at <= ? ORDER BY created_at LIMIT 2000",
                    (started, ended),
                ).fetchall()
                result["session_rows"]["tonho"] = [dict(row) for row in rows]

            if _table_exists(conn, "recording_files") and _table_exists(conn, "events"):
                result["invariants"]["orphan_recording_source_events"] = int(conn.execute(
                    "SELECT COUNT(*) FROM recording_files rf LEFT JOIN events e ON e.id=rf.source_event_id WHERE rf.source_event_id IS NOT NULL AND e.id IS NULL"
                ).fetchone()[0])
            if _table_exists(conn, "face_samples") and _table_exists(conn, "events"):
                result["invariants"]["orphan_face_samples"] = int(conn.execute(
                    "SELECT COUNT(*) FROM face_samples fs LEFT JOIN events e ON e.id=fs.event_id WHERE fs.event_id IS NOT NULL AND e.id IS NULL"
                ).fetchone()[0])
            if _table_exists(conn, "body_samples") and _table_exists(conn, "events"):
                result["invariants"]["orphan_body_samples"] = int(conn.execute(
                    "SELECT COUNT(*) FROM body_samples bs LEFT JOIN events e ON e.id=bs.event_id WHERE bs.event_id IS NOT NULL AND e.id IS NULL"
                ).fetchone()[0])
            if {"identity_origin", "identity_state", "person_id"}.issubset(event_cols):
                result["invariants"]["manual_identity_without_person"] = int(conn.execute(
                    """SELECT COUNT(*) FROM events
                    WHERE lower(COALESCE(identity_origin,'')) LIKE 'manual%'
                      AND COALESCE(identity_state,'') != 'false_positive' AND person_id IS NULL"""
                ).fetchone()[0])
    except Exception as exc:
        result["error"] = str(exc)
    return _sanitize(result)


def _system_sample() -> dict[str, Any]:
    disk = shutil.disk_usage(DATA_DIR)
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return {
        "ts": _now_iso(),
        "kind": "system.sample",
        "data": {
            "process_cpu_seconds": round(time.process_time(), 3),
            "process_uptime_seconds": round(time.monotonic() - _MODULE_STARTED, 3),
            "process_memory_bytes": _process_memory_bytes(),
            "threads": threading.active_count(),
            "disk_total_bytes": disk.total,
            "disk_used_bytes": disk.used,
            "disk_free_bytes": disk.free,
            "database_bytes": db_size,
        },
    }


def _component_sample() -> dict[str, Any]:
    payload: dict[str, Any] = {"ts": _now_iso(), "kind": "components.sample", "data": {}}
    try:
        from .main import (
            alert_manager, assistant_manager, body_identity_manager, identity_manager,
            spatial_alert_manager, vision_manager,
        )
        from .storage_recording import recorder_manager
        with connection() as conn:
            cameras = [dict(row) for row in conn.execute(
                "SELECT id, name, enabled, sync_status, sync_error FROM cameras ORDER BY id"
            ).fetchall()]
        vision: list[dict[str, Any]] = []
        for camera in cameras:
            try:
                vision.append(vision_manager.state(int(camera["id"])))
            except Exception as exc:
                vision.append({"camera_id": camera["id"], "error": str(exc)})
        payload["data"] = {
            "cameras": cameras,
            "vision": vision,
            "identity": identity_manager.state(),
            "body_reid": body_identity_manager.state(),
            "assistant": {"status": assistant_manager.status, "error": assistant_manager.error},
            "alerts": {"status": alert_manager.status, "error": alert_manager.error},
            "spatial_alerts": spatial_alert_manager.state(),
            "recorder": recorder_manager.status(),
        }
    except Exception as exc:
        payload["data"] = {"error": str(exc)}
    return _sanitize(payload)


def _tail_text(path: Path, maximum: int = 256 * 1024) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - maximum), os.SEEK_SET)
            raw = handle.read(maximum)
        text = raw.decode("utf-8", errors="replace")
        return _URL_CREDENTIALS.sub(r"\1***:***@", text)
    except Exception as exc:
        return f"<failed to read log: {exc}>"


class DiagnosticSessionManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.active_id: str | None = None
        self.active_dir: Path | None = None
        self.started_monotonic = 0.0
        DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
        self._finalize_interrupted()

    def _finalize_interrupted(self) -> None:
        for folder in DIAGNOSTICS_DIR.glob("session_*"):
            meta_path = folder / "session.json"
            meta = _read_json(meta_path)
            if meta.get("status") == "active":
                meta["status"] = "interrupted"
                meta["ended_at"] = _now_iso()
                meta["interruption_reason"] = "backend restarted or process ended before diagnostic stop"
                _write_json(meta_path, meta)

    def _folder(self, session_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{8,96}", session_id or ""):
            raise HTTPException(status_code=400, detail="ID de sessão inválido")
        folder = (DIAGNOSTICS_DIR / session_id).resolve()
        if DIAGNOSTICS_DIR.resolve() not in folder.parents:
            raise HTTPException(status_code=400, detail="ID de sessão inválido")
        return folder

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.active_id:
                raise HTTPException(status_code=409, detail=f"Já existe uma sessão de diagnóstico ativa: {self.active_id}")
            mode = str(payload.get("mode") or "full").lower()
            if mode not in {"quick", "full"}:
                mode = "full"
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_id = f"session_{stamp}_{uuid.uuid4().hex[:8]}"
            folder = self._folder(session_id)
            folder.mkdir(parents=True, exist_ok=False)
            meta = {
                "format": "PersonOfInterest full diagnostic session v1",
                "session_id": session_id,
                "status": "active",
                "mode": mode,
                "started_at": _now_iso(),
                "include_tonho_text": bool(payload.get("include_tonho_text")),
                "screen_recording_requested": bool(payload.get("screen_recording")),
                "client": _sanitize(payload.get("client") or {}),
                "runtime": _runtime_info(),
                "privacy": {
                    "raw_embeddings": False,
                    "rtsp_credentials": False,
                    "push_tokens": False,
                    "tonho_text_included": bool(payload.get("include_tonho_text")),
                },
            }
            _write_json(folder / "session.json", meta)
            self.active_id = session_id
            self.active_dir = folder
            self.started_monotonic = time.monotonic()
            _append_jsonl(folder / "component-state.jsonl", _component_sample())
            _append_jsonl(folder / "system.jsonl", _system_sample())
            self._prune()
            return {"session_id": session_id, "status": "active", "mode": mode, "started_at": meta["started_at"]}

    def _prune(self) -> None:
        folders: list[tuple[float, Path]] = []
        for folder in DIAGNOSTICS_DIR.glob("session_*"):
            if self.active_dir and folder == self.active_dir:
                continue
            try:
                folders.append((folder.stat().st_mtime, folder))
            except OSError:
                pass
        for _, folder in sorted(folders, reverse=True)[10:]:
            try:
                shutil.rmtree(folder)
            except OSError:
                pass

    def ensure_active(self, session_id: str) -> Path:
        with self.lock:
            if self.active_id != session_id or self.active_dir is None:
                raise HTTPException(status_code=409, detail="A sessão não está ativa neste processo")
            return self.active_dir

    def add_events(self, session_id: str, events: list[Any]) -> int:
        folder = self.ensure_active(session_id)
        written = 0
        with self.lock:
            for raw in events[:500]:
                if not isinstance(raw, dict):
                    continue
                category = str(raw.get("category") or "frontend-state")
                if category not in ALLOWED_CATEGORIES:
                    category = "frontend-state"
                entry = {
                    "ts": raw.get("ts") or _now_iso(),
                    "received_at": _now_iso(),
                    "kind": str(raw.get("kind") or "event")[:160],
                    "data": _sanitize(raw.get("data") or {}),
                }
                _append_jsonl(folder / f"{category}.jsonl", entry)
                written += 1
        return written

    def sample(self, session_id: str) -> None:
        folder = self.ensure_active(session_id)
        with self.lock:
            _append_jsonl(folder / "system.jsonl", _system_sample())
            _append_jsonl(folder / "component-state.jsonl", _component_sample())

    def marker(self, session_id: str, note: str | None) -> dict[str, Any]:
        folder = self.ensure_active(session_id)
        entry = {"ts": _now_iso(), "kind": "user.problem_marker", "data": {"note": (note or "").strip()[:500]}}
        with self.lock:
            _append_jsonl(folder / "markers.jsonl", entry)
        return entry

    def screen_path(self, session_id: str) -> Path:
        return self.ensure_active(session_id) / "screen.webm"

    def server_error(self, kind: str, exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
        with self.lock:
            if not self.active_dir:
                return
            text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            _append_jsonl(self.active_dir / "backend-errors.jsonl", {
                "ts": _now_iso(), "kind": kind, "data": {"exception": text[-12000:]},
            })

    def stop(self, session_id: str) -> dict[str, Any]:
        folder = self.ensure_active(session_id)
        with self.lock:
            meta_path = folder / "session.json"
            meta = _read_json(meta_path)
            meta["status"] = "completed"
            meta["ended_at"] = _now_iso()
            meta["duration_seconds"] = round(time.monotonic() - self.started_monotonic, 3)
            meta["screen_recording_included"] = (folder / "screen.webm").is_file()
            _write_json(meta_path, meta)
            _write_json(folder / "db-summary.json", _db_summary(meta))
            self._capture_logs(folder)
            self.active_id = None
            self.active_dir = None
            self.started_monotonic = 0.0
        return {"session_id": session_id, "status": "completed", "export_url": f"/api/diagnostics/session/{session_id}/export"}

    def _capture_logs(self, folder: Path) -> None:
        source = DATA_DIR / "logs"
        if not source.is_dir():
            return
        target = folder / "logs"
        target.mkdir(exist_ok=True)
        for path in sorted(source.glob("*.log"))[:50]:
            (target / path.name).write_text(_tail_text(path), encoding="utf-8")

    def status(self) -> dict[str, Any]:
        active = None
        with self.lock:
            if self.active_id and self.active_dir:
                active = _read_json(self.active_dir / "session.json")
        previous: list[dict[str, Any]] = []
        for folder in sorted(DIAGNOSTICS_DIR.glob("session_*"), key=lambda p: p.stat().st_mtime, reverse=True):
            meta = _read_json(folder / "session.json")
            if not meta or meta.get("session_id") == self.active_id:
                continue
            previous.append({
                "session_id": meta.get("session_id") or folder.name,
                "status": meta.get("status"),
                "started_at": meta.get("started_at"),
                "ended_at": meta.get("ended_at"),
                "mode": meta.get("mode"),
                "export_url": f"/api/diagnostics/session/{folder.name}/export",
            })
            if len(previous) >= 3:
                break
        return {"active": active, "previous": previous}

    def export(self, session_id: str) -> Path:
        folder = self._folder(session_id)
        if not folder.is_dir():
            raise HTTPException(status_code=404, detail="Sessão não encontrada")
        meta = _read_json(folder / "session.json")
        if not meta:
            raise HTTPException(status_code=404, detail="Metadados da sessão não encontrados")
        if meta.get("status") == "active" and session_id == self.active_id:
            raise HTTPException(status_code=409, detail="Encerre a sessão antes de exportar")
        if not (folder / "db-summary.json").exists():
            _write_json(folder / "db-summary.json", _db_summary(meta))
            self._capture_logs(folder)
        report = self._report(folder, meta)
        (folder / "diagnostic-report.html").write_text(report, encoding="utf-8")
        (folder / "README.txt").write_text(
            "PersonOfInterest diagnostic session\n\n"
            "session.json: ambiente e duração\n"
            "frontend-actions.jsonl: ações semânticas do usuário\n"
            "frontend-state.jsonl: snapshots de estado da UI\n"
            "performance.jsonl: FPS, long tasks e memória do navegador\n"
            "media.jsonl: play/pause/seek/wait/stall e qualidade de vídeo\n"
            "api.jsonl: duração/status das chamadas HTTP vistas pelo frontend\n"
            "system.jsonl: processo, disco, threads e banco\n"
            "component-state.jsonl: visão, tracks, ReID, Tonho, alertas e recorder\n"
            "markers.jsonl: instantes marcados manualmente como problema\n"
            "db-summary.json: contagens, invariantes e registros do período\n"
            "logs/: caudas sanitizadas dos logs locais\n"
            "screen.webm: gravação de tela, somente se solicitada\n",
            encoding="utf-8",
        )
        zip_path = folder / f"{session_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=5, allowZip64=True) as archive:
            for path in folder.rglob("*"):
                if not path.is_file() or path == zip_path:
                    continue
                archive.write(path, path.relative_to(folder).as_posix())
        return zip_path

    def _report(self, folder: Path, meta: dict[str, Any]) -> str:
        counts: dict[str, int] = {}
        for path in folder.glob("*.jsonl"):
            try:
                counts[path.name] = sum(1 for line in path.open("r", encoding="utf-8") if line.strip())
            except Exception:
                counts[path.name] = 0
        db = _read_json(folder / "db-summary.json")
        invariants = db.get("invariants") or {}
        event_count = len((db.get("session_rows") or {}).get("events") or [])
        recording_count = len((db.get("session_rows") or {}).get("recordings") or [])
        tonho_count = len((db.get("session_rows") or {}).get("tonho") or [])
        rows = "".join(f"<tr><td>{html.escape(name)}</td><td>{value}</td></tr>" for name, value in sorted(counts.items()))
        inv = "".join(f"<tr><td>{html.escape(str(name))}</td><td>{html.escape(str(value))}</td></tr>" for name, value in invariants.items())
        return f"""<!doctype html><meta charset='utf-8'><title>PersonOfInterest diagnóstico</title>
<style>body{{font:15px system-ui;max-width:1000px;margin:40px auto;padding:0 20px;background:#0d1117;color:#e6edf3}}table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}td,th{{border:1px solid #30363d;padding:8px;text-align:left}}code{{background:#161b22;padding:2px 5px;border-radius:4px}}.ok{{color:#3fb950}}</style>
<h1>PersonOfInterest · sessão de diagnóstico</h1>
<p><code>{html.escape(str(meta.get('session_id')))}</code> · {html.escape(str(meta.get('status')))} · modo {html.escape(str(meta.get('mode')))}</p>
<p>Início: {html.escape(str(meta.get('started_at')))}<br>Fim: {html.escape(str(meta.get('ended_at')))}<br>Duração: {html.escape(str(meta.get('duration_seconds','—')))} s</p>
<h2>Resumo do período</h2><p>{event_count} eventos · {recording_count} gravações · {tonho_count} registros Tonho</p>
<h2>Telemetria</h2><table><tr><th>Arquivo</th><th>Registros</th></tr>{rows}</table>
<h2>Invariantes do banco</h2><table><tr><th>Verificação</th><th>Ocorrências</th></tr>{inv or '<tr><td colspan=2>Sem dados</td></tr>'}</table>
<p class='ok'>Abra os JSONL correlacionando pelo timestamp e pelos marcadores manuais.</p>"""


manager = DiagnosticSessionManager()


@router.get("/status")
def diagnostic_status() -> dict[str, Any]:
    return manager.status()


@router.post("/start")
async def diagnostic_start(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return manager.start(payload)


@router.post("/{session_id}/events")
async def diagnostic_events(session_id: str, request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_EVENT_BODY:
        raise HTTPException(status_code=413, detail="Lote de diagnóstico muito grande")
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="events deve ser uma lista")
    return {"written": manager.add_events(session_id, events)}


@router.post("/{session_id}/sample")
def diagnostic_sample(session_id: str) -> dict[str, Any]:
    manager.sample(session_id)
    return {"ok": True}


@router.post("/{session_id}/marker")
async def diagnostic_marker(session_id: str, request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    note = payload.get("note") if isinstance(payload, dict) else None
    return manager.marker(session_id, str(note or ""))


@router.post("/{session_id}/screen")
async def diagnostic_screen(session_id: str, request: Request) -> dict[str, Any]:
    content_length = int(request.headers.get("content-length") or 0)
    if content_length > MAX_SCREEN_BYTES:
        raise HTTPException(status_code=413, detail="Gravação de tela excede 250 MB")
    body = await request.body()
    if len(body) > MAX_SCREEN_BYTES:
        raise HTTPException(status_code=413, detail="Gravação de tela excede 250 MB")
    path = manager.screen_path(session_id)
    path.write_bytes(body)
    return {"ok": True, "bytes": len(body)}


@router.post("/{session_id}/stop")
def diagnostic_stop(session_id: str) -> dict[str, Any]:
    return manager.stop(session_id)


@router.get("/{session_id}/export")
def diagnostic_export(session_id: str) -> FileResponse:
    path = manager.export(session_id)
    return FileResponse(path, media_type="application/zip", filename=path.name)

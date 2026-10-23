from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from .db import connection
from .storage_recording import RECORDINGS_DIR, recorder_manager, seconds_for


router = APIRouter(tags=["timeline-player"])
_CONTINUOUS_RE = re.compile(r"continuous_cam(?P<camera>\d+)_(?P<stamp>\d{8}_%H%M%S)\.mp4$", re.IGNORECASE)


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


def _server_local_tz() -> Any:
    return datetime.now().astimezone().tzinfo or timezone.utc


def _continuous_start(row: dict[str, Any], segment_seconds: float) -> datetime | None:
    name = Path(str(row.get("path") or "")).name
    match = _CONTINUOUS_RE.match(name)
    if match:
        try:
            local = datetime.strptime(match.group("stamp"), "%Y%m%d_%H%M%S").replace(tzinfo=_server_local_tz())
            parsed = local.astimezone(timezone.utc)
            path = (RECORDINGS_DIR / str(row.get("path") or "")).resolve()
            if path.is_file():
                mtime_start = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) - timedelta(seconds=segment_seconds)
                if abs((parsed - mtime_start).total_seconds()) > 6 * 3600:
                    return mtime_start
            return parsed
        except Exception:
            pass
    ended = _parse_iso(row.get("ended_at")) or _parse_iso(row.get("updated_at"))
    if ended is not None:
        return ended - timedelta(seconds=segment_seconds)
    return _parse_iso(row.get("started_at")) or _parse_iso(row.get("created_at"))


def _event_label(row: Any) -> str:
    if row["person_name"]:
        return str(row["person_name"])
    if row["probable_person_name"]:
        return f"{row['probable_person_name']}?"
    if str(row["identity_state"] or "") == "false_positive":
        return "Falso positivo"
    return "Pessoa"


@router.get("/api/timeline-player/recordings/{recording_id}")
def timeline_recording_stream(recording_id: int) -> FileResponse:
    """Inline MP4 endpoint used by the day player.

    It intentionally omits a download filename so browsers can seek it as media.
    Starlette FileResponse supplies byte-range support on supported runtime versions.
    """
    path = recorder_manager.recording_path(recording_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Gravação não encontrada")
    return FileResponse(path, media_type="video/mp4")


@router.get("/api/timeline-player/day")
def timeline_player_day(
    camera_id: int = Query(ge=1),
    date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    utc_offset_minutes: int = Query(default=0, ge=-840, le=840),
) -> dict[str, Any]:
    try:
        requested_day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Data inválida") from exc

    local_tz = timezone(timedelta(minutes=int(utc_offset_minutes)))
    local_start = datetime.combine(requested_day, datetime.min.time(), tzinfo=local_tz)
    local_end = local_start + timedelta(days=1)
    start_utc = local_start.astimezone(timezone.utc)
    end_utc = local_end.astimezone(timezone.utc)
    duration_seconds = max(1.0, (end_utc - start_utc).total_seconds())

    recorder_manager.ensure_schema()
    query_start = (start_utc - timedelta(days=1)).isoformat()
    query_end = (end_utc + timedelta(days=1)).isoformat()
    with connection() as conn:
        camera = conn.execute(
            "SELECT id, name, location, enabled, sync_status FROM cameras WHERE id = ?",
            (int(camera_id),),
        ).fetchone()
        if camera is None:
            raise HTTPException(status_code=404, detail="Câmera não encontrada")
        setting = conn.execute(
            "SELECT * FROM recording_settings WHERE camera_id = ?",
            (int(camera_id),),
        ).fetchone()
        events = conn.execute(
            """SELECT e.id, e.camera_id, e.track_id, e.event_type, e.person_id,
                e.probable_person_id, e.identity_state, e.identity_confidence,
                e.body_confidence, e.has_face, e.snapshot_path, e.created_at,
                p.name AS person_name, pp.name AS probable_person_name
            FROM events e
            LEFT JOIN persons p ON p.id = e.person_id
            LEFT JOIN persons pp ON pp.id = e.probable_person_id
            WHERE e.camera_id = ? AND e.created_at >= ? AND e.created_at < ?
            ORDER BY e.created_at ASC""",
            (int(camera_id), start_utc.isoformat(), end_utc.isoformat()),
        ).fetchall()
        recording_rows = conn.execute(
            """SELECT * FROM recording_files
            WHERE camera_id = ?
              AND COALESCE(created_at, started_at, updated_at) >= ?
              AND COALESCE(created_at, started_at, updated_at) < ?
            ORDER BY COALESCE(started_at, created_at) ASC""",
            (int(camera_id), query_start, query_end),
        ).fetchall()
        recording_link_rows = conn.execute(
            """SELECT rel.recording_id, rel.event_id, e.identity_state
            FROM recording_event_links rel
            JOIN recording_files rf ON rf.id = rel.recording_id
            JOIN events e ON e.id = rel.event_id
            WHERE rf.camera_id = ?
              AND COALESCE(rf.created_at, rf.started_at, rf.updated_at) >= ?
              AND COALESCE(rf.created_at, rf.started_at, rf.updated_at) < ?
            ORDER BY rel.recording_id, e.created_at ASC""",
            (int(camera_id), query_start, query_end),
        ).fetchall()

    event_to_recordings: dict[int, list[int]] = {}
    recording_to_events: dict[int, list[int]] = {}
    recording_event_states: dict[int, list[str]] = {}
    for link in recording_link_rows:
        recording_id = int(link["recording_id"])
        event_id = int(link["event_id"])
        event_to_recordings.setdefault(event_id, []).append(recording_id)
        recording_to_events.setdefault(recording_id, []).append(event_id)
        recording_event_states.setdefault(recording_id, []).append(str(link["identity_state"] or ""))

    setting_data = dict(setting) if setting else {
        "camera_id": int(camera_id),
        "mode": "off",
        "event_duration_value": 60,
        "event_duration_unit": "seconds",
        "segment_duration_value": 5,
        "segment_duration_unit": "minutes",
    }
    segment_seconds = max(
        10.0,
        seconds_for(setting_data.get("segment_duration_value", 5), setting_data.get("segment_duration_unit", "minutes")),
    )

    normalized: list[dict[str, Any]] = []
    continuous_candidates: list[tuple[datetime, dict[str, Any]]] = []
    event_candidates: list[tuple[datetime, datetime, dict[str, Any]]] = []

    for raw in recording_rows:
        row = dict(raw)
        mode = str(row.get("mode") or "")
        if mode == "continuous":
            started = _continuous_start(row, segment_seconds)
            if started is not None:
                continuous_candidates.append((started, row))
        else:
            started = _parse_iso(row.get("started_at")) or _parse_iso(row.get("created_at"))
            if started is None:
                continue
            ended = _parse_iso(row.get("ended_at"))
            if ended is None:
                seconds = float(row.get("duration_seconds") or 0.0)
                ended = started + timedelta(seconds=max(1.0, seconds))
            event_candidates.append((started, max(started, ended), row))

    continuous_candidates.sort(key=lambda item: item[0])
    active_camera_ids = {
        int(item["camera_id"])
        for item in recorder_manager.status().get("sessions", [])
        if item.get("running") and item.get("mode") == "continuous"
    }
    now_utc = datetime.now(timezone.utc)

    for index, (started, row) in enumerate(continuous_candidates):
        expected_end = started + timedelta(seconds=segment_seconds)
        if index + 1 < len(continuous_candidates):
            next_start = continuous_candidates[index + 1][0]
            if started < next_start <= started + timedelta(seconds=segment_seconds * 1.8):
                expected_end = next_start
        is_latest = index == len(continuous_candidates) - 1
        is_active = int(camera_id) in active_camera_ids and is_latest and expected_end >= now_utc - timedelta(seconds=segment_seconds * 1.5)
        ended = min(now_utc, expected_end) if is_active else expected_end
        if ended <= start_utc or started >= end_utc:
            continue
        relative = str(row.get("path") or "")
        path = (RECORDINGS_DIR / relative).resolve()
        file_exists = RECORDINGS_DIR.resolve() in path.parents and path.is_file()
        normalized.append({
            "id": int(row["id"]),
            "mode": "continuous",
            "source_event_id": row.get("source_event_id"),
            "event_ids": [],
            "false_positive_only": False,
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "start_second": max(0.0, (started - start_utc).total_seconds()),
            "end_second": min(duration_seconds, (ended - start_utc).total_seconds()),
            "duration_seconds": max(0.0, (ended - started).total_seconds()),
            "size_bytes": int(row.get("size_bytes") or 0),
            "status": "active" if is_active else "complete",
            "file_url": None if is_active else (f"/api/timeline-player/recordings/{int(row['id'])}" if file_exists else None),
        })

    for started, ended, row in event_candidates:
        if ended <= start_utc or started >= end_utc:
            continue
        relative = str(row.get("path") or "")
        path = (RECORDINGS_DIR / relative).resolve()
        file_exists = RECORDINGS_DIR.resolve() in path.parents and path.is_file()
        recording_id = int(row["id"])
        event_ids = list(recording_to_events.get(recording_id, []))
        if not event_ids and row.get("source_event_id") is not None:
            event_ids = [int(row["source_event_id"])]
        states = recording_event_states.get(recording_id, [])
        false_positive_only = bool(states) and all(state == "false_positive" for state in states)
        normalized.append({
            "id": recording_id,
            "mode": "event",
            "source_event_id": row.get("source_event_id"),
            "event_ids": event_ids,
            "false_positive_only": false_positive_only,
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "start_second": max(0.0, (started - start_utc).total_seconds()),
            "end_second": min(duration_seconds, (ended - start_utc).total_seconds()),
            "duration_seconds": max(0.0, (ended - started).total_seconds()),
            "size_bytes": int(row.get("size_bytes") or 0),
            "status": str(row.get("status") or "complete"),
            "file_url": f"/api/timeline-player/recordings/{recording_id}" if file_exists else None,
        })

    normalized.sort(key=lambda item: (float(item["start_second"]), int(item["id"])))
    normalized_by_id = {int(item["id"]): item for item in normalized}

    event_items: list[dict[str, Any]] = []
    for row in events:
        created = _parse_iso(row["created_at"])
        if created is None:
            continue
        event_id = int(row["id"])
        second = min(duration_seconds, max(0.0, (created - start_utc).total_seconds()))
        explicit = next(
            (
                normalized_by_id[recording_id]
                for recording_id in event_to_recordings.get(event_id, [])
                if recording_id in normalized_by_id and normalized_by_id[recording_id].get("file_url")
            ),
            None,
        )
        source_exact = next(
            (
                rec for rec in normalized
                if rec.get("source_event_id") == event_id and rec.get("file_url")
            ),
            None,
        )
        # Event clips are never inferred by time: overlapping event clips made
        # that association ambiguous and could link a false positive to another
        # event's recording. Time containment remains valid only for continuous
        # recordings, where the file genuinely represents the whole interval.
        continuous_cover = next(
            (
                rec for rec in normalized
                if rec.get("mode") == "continuous"
                and float(rec["start_second"]) <= second <= float(rec["end_second"])
                and rec.get("file_url")
            ),
            None,
        )
        covered = explicit or source_exact or continuous_cover
        event_items.append({
            "id": event_id,
            "camera_id": int(row["camera_id"]),
            "track_id": row["track_id"],
            "event_type": row["event_type"],
            "person_id": row["person_id"],
            "probable_person_id": row["probable_person_id"],
            "identity_state": row["identity_state"],
            "identity_confidence": row["identity_confidence"],
            "body_confidence": row["body_confidence"],
            "has_face": bool(row["has_face"]),
            "created_at": created.isoformat(),
            "second": second,
            "label": _event_label(row),
            "snapshot_url": f"/api/events/{event_id}/snapshot" if row["snapshot_path"] else None,
            "recording_id": covered["id"] if covered else None,
            "recording_mode": covered["mode"] if covered else None,
            "recording_offset_seconds": max(0.0, second - float(covered["start_second"])) if covered else None,
        })

    local_now = now_utc.astimezone(local_tz)
    is_today = local_now.date() == requested_day
    now_second = min(duration_seconds, max(0.0, (now_utc - start_utc).total_seconds())) if is_today else None

    return {
        "camera": {
            "id": int(camera["id"]),
            "name": camera["name"],
            "location": camera["location"],
            "enabled": bool(camera["enabled"]),
            "sync_status": camera["sync_status"],
        },
        "recording": {
            **setting_data,
            "mode": str(setting_data.get("mode") or "off"),
            "continuous_active": int(camera_id) in active_camera_ids,
        },
        "date": date,
        "utc_offset_minutes": int(utc_offset_minutes),
        "day_start": start_utc.isoformat(),
        "day_end": end_utc.isoformat(),
        "day_duration_seconds": duration_seconds,
        "is_today": is_today,
        "now_second": now_second,
        "recordings": normalized,
        "events": event_items,
        "false_positive_count": sum(1 for item in event_items if item.get("identity_state") == "false_positive"),
    }

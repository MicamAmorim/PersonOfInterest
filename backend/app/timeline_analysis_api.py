from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .config import WAKE_CONVERSATION_SECONDS
from .db import connection
from .wake_word import matches_wake_phrase


router = APIRouter(tags=["timeline-analysis"])


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


def _bbox(raw: Any) -> dict[str, float] | None:
    if not raw:
        return None
    try:
        data = json.loads(str(raw)) if not isinstance(raw, dict) else raw
        values = {key: float(data[key]) for key in ("x", "y", "w", "h")}
        if values["w"] <= 0 or values["h"] <= 0:
            return None
        return values
    except Exception:
        return None


def _speech_seconds(text: str | None) -> float:
    # Only used to give a conversation marker a useful visible width.
    size = len((text or "").strip())
    return max(3.0, min(15.0, 1.8 + size / 14.0))


def _table_exists(conn: Any, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone() is not None


@router.get("/api/timeline-player/analysis")
def timeline_analysis(
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
    duration = max(1.0, (end_utc - start_utc).total_seconds())

    with connection() as conn:
        camera = conn.execute("SELECT id, name FROM cameras WHERE id = ?", (int(camera_id),)).fetchone()
        if camera is None:
            raise HTTPException(status_code=404, detail="Câmera não encontrada")

        # events.bbox_json follows the best display snapshot and may therefore be
        # updated later in a track. For video overlays we need the trigger-time box.
        # The first observation persisted for an event is the closest available
        # observation to that event's trigger and avoids a SQLite correlated ORDER BY
        # that cannot reliably reference the outer alias on all supported versions.
        if _table_exists(conn, "track_observations"):
            trigger_bbox_select = """
                (SELECT t.bbox_json
                 FROM track_observations t
                 WHERE t.event_id = e.id
                 ORDER BY t.created_at ASC, t.id ASC
                 LIMIT 1) AS trigger_bbox_json,
            """
        else:
            trigger_bbox_select = "NULL AS trigger_bbox_json,"

        event_rows = conn.execute(
            f"""SELECT e.id, e.created_at, e.bbox_json, {trigger_bbox_select}
                e.snapshot_path, e.identity_state, e.person_id, e.probable_person_id,
                p.name AS person_name, pp.name AS probable_person_name
            FROM events e
            LEFT JOIN persons p ON p.id = e.person_id
            LEFT JOIN persons pp ON pp.id = e.probable_person_id
            WHERE e.camera_id = ? AND e.created_at >= ? AND e.created_at < ?
            ORDER BY e.created_at ASC""",
            (int(camera_id), start_utc.isoformat(), end_utc.isoformat()),
        ).fetchall()

        clip_event_ids: set[int] = set()
        if _table_exists(conn, "recording_files"):
            clip_event_ids = {
                int(row["source_event_id"])
                for row in conn.execute(
                    """SELECT DISTINCT source_event_id FROM recording_files
                    WHERE camera_id = ? AND mode = 'event' AND source_event_id IS NOT NULL""",
                    (int(camera_id),),
                ).fetchall()
                if row["source_event_id"] is not None
            }

        wake_rows: list[Any] = []
        if _table_exists(conn, "assistant_wake_log"):
            wake_rows = conn.execute(
                """SELECT w.id, w.camera_id, w.transcript, w.response_text, w.certainty,
                    w.person_id, w.created_at, p.name AS person_name
                FROM assistant_wake_log w
                LEFT JOIN persons p ON p.id = w.person_id
                WHERE w.camera_id = ? AND w.matched = 1
                  AND w.created_at >= ? AND w.created_at < ?
                ORDER BY w.created_at ASC, w.id ASC""",
                (int(camera_id), start_utc.isoformat(), end_utc.isoformat()),
            ).fetchall()

    events: list[dict[str, Any]] = []
    for row in event_rows:
        created = _parse_iso(row["created_at"])
        if created is None:
            continue
        second = max(0.0, min(duration, (created - start_utc).total_seconds()))
        label = row["person_name"] or (f"{row['probable_person_name']}?" if row["probable_person_name"] else None)
        if not label:
            label = "Falso positivo" if str(row["identity_state"] or "") == "false_positive" else "Pessoa"
        trigger_bbox = _bbox(row["trigger_bbox_json"])
        display_bbox = _bbox(row["bbox_json"])
        events.append({
            "id": int(row["id"]),
            "second": second,
            "label": str(label),
            "bbox": trigger_bbox or display_bbox,
            "bbox_source": "trigger_observation" if trigger_bbox else ("event_display" if display_bbox else None),
            "snapshot_url": f"/api/events/{int(row['id'])}/snapshot" if row["snapshot_path"] else None,
            "has_clip": int(row["id"]) in clip_event_ids,
            "identity_state": row["identity_state"],
        })

    # Reconstruct only sessions that genuinely started with the wake phrase.
    # This also makes historical logs useful without altering the wake-word motor.
    sessions: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    last_at: datetime | None = None
    max_followup_gap = max(20.0, min(120.0, float(WAKE_CONVERSATION_SECONDS) * 3.0 + 12.0))

    def finish() -> None:
        nonlocal active
        if not active:
            return
        active["end_second"] = min(duration, max(float(active["end_second"]), float(active["start_second"]) + 4.0))
        active["duration_seconds"] = max(0.0, float(active["end_second"]) - float(active["start_second"]))
        sessions.append(active)
        active = None

    for row in wake_rows:
        created = _parse_iso(row["created_at"])
        if created is None:
            continue
        second = max(0.0, min(duration, (created - start_utc).total_seconds()))
        transcript = str(row["transcript"] or "").strip()
        response = str(row["response_text"] or "").strip()
        wake_start = matches_wake_phrase(transcript)

        if wake_start:
            finish()
            active = {
                "id": int(row["id"]),
                "start_second": second,
                "end_second": min(duration, second + _speech_seconds(response)),
                "created_at": created.isoformat(),
                "person_id": row["person_id"],
                "person_name": row["person_name"],
                "turns": [],
            }
        elif active is None or last_at is None or (created - last_at).total_seconds() > max_followup_gap:
            last_at = created
            continue

        if active is not None:
            active["turns"].append({
                "id": int(row["id"]),
                "second": second,
                "user": transcript,
                "tonho": response,
                "certainty": row["certainty"],
                "person_id": row["person_id"],
                "person_name": row["person_name"],
            })
            active["end_second"] = min(duration, max(float(active["end_second"]), second + _speech_seconds(response)))
        last_at = created

    finish()

    return {
        "camera": {"id": int(camera["id"]), "name": str(camera["name"])},
        "date": date,
        "day_duration_seconds": duration,
        "events": events,
        "audio_sessions": sessions,
    }

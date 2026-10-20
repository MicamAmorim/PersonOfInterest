from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import false_positive_memory
from .body_identity import manager as body_identity_manager
from .db import connection
from .storage_recording import recorder_manager, storage_manager


router = APIRouter()


class StorageSettingsUpdate(BaseModel):
    cleanup_enabled: bool | None = None
    timeline_retention_value: float | None = None
    timeline_retention_unit: str | None = None
    timeline_max_gb: float | None = None
    face_auto_limit_per_person: int | None = None
    body_auto_limit_per_person: int | None = None
    protect_manual: bool | None = None
    cleanup_interval_minutes: float | None = None
    false_positive_max_prototypes_per_camera: int | None = None
    false_positive_examples_per_prototype: int | None = None
    recording_retention_value: float | None = None
    recording_retention_unit: str | None = None
    recording_max_gb: float | None = None
    disk_reserve_gb: float | None = None


class RecordingSettingsUpdate(BaseModel):
    mode: str | None = None
    event_duration_value: float | None = None
    event_duration_unit: str | None = None
    segment_duration_value: float | None = None
    segment_duration_unit: str | None = None


class PrototypeStateUpdate(BaseModel):
    active: bool


@router.get("/api/storage/settings")
def get_storage_settings() -> dict:
    return storage_manager.settings()


@router.put("/api/storage/settings")
def update_storage_settings(payload: StorageSettingsUpdate) -> dict:
    try:
        values = payload.model_dump(exclude_none=True)
        return storage_manager.update_settings(values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/storage/status")
def storage_status() -> dict:
    return storage_manager.status()


@router.post("/api/storage/cleanup")
def run_storage_cleanup() -> dict:
    return storage_manager.cleanup_now()


@router.get("/api/storage/events")
def storage_timeline_events(
    camera_id: int | None = Query(default=None, ge=1),
    person_id: int | None = Query(default=None, ge=1),
    unidentified: bool = False,
    from_ts: str | None = None,
    to_ts: str | None = None,
    has_face: bool | None = None,
    false_positive_mode: str = Query(default="normal", pattern="^(normal|false|all)$"),
    limit: int = Query(default=500, ge=1, le=500),
) -> list[dict]:
    """Timeline view that keeps learned false positives out of the normal feed."""
    sql = """SELECT e.*, c.name AS camera_name, c.location AS camera_location,
        p.name AS person_name, pp.name AS probable_person_name
        FROM events e
        JOIN cameras c ON c.id = e.camera_id
        LEFT JOIN persons p ON p.id = e.person_id
        LEFT JOIN persons pp ON pp.id = e.probable_person_id"""
    where: list[str] = []
    params: list[object] = []
    if false_positive_mode == "normal":
        where.append("COALESCE(e.identity_state, '') <> 'false_positive'")
    elif false_positive_mode == "false":
        where.append("COALESCE(e.identity_state, '') = 'false_positive'")
    if camera_id is not None:
        where.append("e.camera_id = ?")
        params.append(camera_id)
    if person_id is not None:
        where.append("(e.person_id = ? OR (e.person_id IS NULL AND e.probable_person_id = ?))")
        params.extend([person_id, person_id])
    elif unidentified:
        where.append("e.person_id IS NULL")
    if from_ts:
        where.append("e.created_at >= ?")
        params.append(from_ts)
    if to_ts:
        where.append("e.created_at <= ?")
        params.append(to_ts)
    if has_face is not None:
        where.append("e.has_face = ?")
        params.append(int(has_face))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY e.created_at DESC LIMIT ?"
    params.append(limit)
    with connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": row["id"],
            "camera_id": row["camera_id"],
            "camera_name": row["camera_name"],
            "camera_location": row["camera_location"],
            "track_id": row["track_id"],
            "event_type": row["event_type"],
            "person_id": row["person_id"],
            "person_name": row["person_name"],
            "probable_person_id": row["probable_person_id"],
            "probable_person_name": row["probable_person_name"],
            "body_confidence": row["body_confidence"],
            "body_identity_source": row["body_identity_source"],
            "unknown_cluster_id": row["unknown_cluster_id"],
            "identity_state": row["identity_state"],
            "identity_confidence": row["identity_confidence"],
            "has_face": bool(row["has_face"]),
            "face_count": row["face_count"],
            "confidence": row["confidence"],
            "created_at": row["created_at"],
            "snapshot_url": f"/api/events/{row['id']}/snapshot" if row["snapshot_path"] else None,
        }
        for row in rows
    ]


@router.get("/api/recording/settings")
def recording_settings() -> list[dict]:
    return recorder_manager.settings()


@router.put("/api/recording/cameras/{camera_id}")
def update_recording_camera(camera_id: int, payload: RecordingSettingsUpdate) -> dict:
    try:
        return recorder_manager.update_camera_settings(camera_id, payload.model_dump(exclude_none=True))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/recording/status")
def recording_status() -> dict:
    return recorder_manager.status()


@router.get("/api/recordings")
def list_recordings(
    camera_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict]:
    return recorder_manager.list_recordings(camera_id=camera_id, limit=limit)


@router.get("/api/recordings/{recording_id}/file")
def recording_file(recording_id: int) -> FileResponse:
    path = recorder_manager.recording_path(recording_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Gravação não encontrada")
    return FileResponse(path, media_type="video/mp4", filename=Path(path).name)


@router.get("/api/false-positives/prototypes")
def list_false_positive_prototypes() -> list[dict]:
    return false_positive_memory.list_prototypes()


@router.get("/api/false-positives/prototypes/{prototype_id}/image")
def false_positive_prototype_image(prototype_id: int) -> FileResponse:
    path = false_positive_memory.prototype_image_path(prototype_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Imagem do falso positivo não encontrada")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.put("/api/false-positives/prototypes/{prototype_id}/state")
def set_false_positive_prototype_state(prototype_id: int, payload: PrototypeStateUpdate) -> dict:
    ok = (
        false_positive_memory.activate_prototype(prototype_id)
        if payload.active
        else false_positive_memory.deactivate_prototype(prototype_id)
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Protótipo de falso positivo não encontrado")
    body_identity_manager.notify_change()
    return {"ok": True, "prototype_id": int(prototype_id), "active": bool(payload.active)}


@router.post("/api/false-positives/backfill")
def backfill_false_positive_memory() -> dict:
    result = false_positive_memory.backfill_existing(body_identity_manager)
    body_identity_manager.notify_change()
    return {"ok": True, **result}

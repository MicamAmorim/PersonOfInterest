from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import false_positive_memory
from .body_identity import manager as body_identity_manager
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

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from .doorbell import DINGDONG_FILENAME, manager


router = APIRouter()


class DoorbellSettingsPayload(BaseModel):
    target_mode: Literal["all", "selected"] = "all"
    camera_ids: list[int] = Field(default_factory=list)
    spatial_dingdong: bool = True
    spatial_voice: bool = True


class DoorbellRingPayload(BaseModel):
    local_name: str = Field(default="", max_length=80)
    dingdong: bool = True
    voice: bool = False

    @model_validator(mode="after")
    def validate_output(self) -> "DoorbellRingPayload":
        if not self.dingdong and not self.voice:
            raise ValueError("Ative o ding-dong, a mensagem de voz ou ambos")
        if self.voice and not self.local_name.strip():
            raise ValueError("Informe o nome deste aparelho para usar a mensagem de voz")
        return self


class SpatialDoorbellPayload(BaseModel):
    enabled: bool


@router.get("/api/doorbell/settings")
def get_doorbell_settings() -> dict:
    return manager.settings()


@router.put("/api/doorbell/settings")
def update_doorbell_settings(payload: DoorbellSettingsPayload) -> dict:
    try:
        return manager.update_settings(
            target_mode=payload.target_mode,
            camera_ids=payload.camera_ids,
            spatial_dingdong=payload.spatial_dingdong,
            spatial_voice=payload.spatial_voice,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/doorbell/ring")
def ring_doorbell(payload: DoorbellRingPayload) -> dict:
    try:
        result = manager.queue_ring(
            local_name=payload.local_name,
            dingdong=payload.dingdong,
            voice=payload.voice,
            source="manual",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("queued"):
        raise HTTPException(status_code=409, detail="Nenhum alto-falante de câmera está disponível agora")
    return result


@router.get("/api/doorbell/spatial-rules")
def list_doorbell_spatial_rules() -> list[dict]:
    return manager.spatial_rules()


@router.put("/api/doorbell/spatial-rules/{rule_id}")
def set_doorbell_spatial_rule(rule_id: int, payload: SpatialDoorbellPayload) -> dict:
    try:
        return manager.set_spatial_rule(rule_id, payload.enabled)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/doorbell/events")
def list_doorbell_events(limit: int = 30) -> list[dict]:
    return manager.list_events(limit)


@router.get("/api/doorbell/audio/{filename}")
def doorbell_audio(filename: str) -> FileResponse:
    if filename != DINGDONG_FILENAME:
        raise HTTPException(status_code=404, detail="Áudio de campainha não encontrado")
    path = manager.chime_path()
    return FileResponse(path, media_type="audio/wav", filename=DINGDONG_FILENAME)

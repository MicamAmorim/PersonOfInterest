from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .assistant import manager as assistant_manager


router = APIRouter()


class AssistantSettingsUpdate(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=30, ge=1, le=1440)
    voice_gender: Literal["female", "male"] = "female"
    timezone: str = Field(default="UTC", min_length=1, max_length=80)


@router.get("/api/assistant/status")
def assistant_status() -> dict:
    return assistant_manager.state()


@router.get("/api/assistant/settings")
def assistant_settings() -> list[dict]:
    return assistant_manager.list_settings()


@router.patch("/api/assistant/cameras/{camera_id}")
def update_assistant_camera(camera_id: int, payload: AssistantSettingsUpdate) -> dict:
    try:
        return assistant_manager.update_settings(
            camera_id,
            enabled=payload.enabled,
            interval_minutes=payload.interval_minutes,
            voice_gender=payload.voice_gender,
            timezone_name=payload.timezone,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/assistant/cameras/{camera_id}/test")
def test_assistant_camera(camera_id: int) -> dict:
    try:
        return assistant_manager.speak_test(camera_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/assistant/audio/{filename}", include_in_schema=False)
def assistant_audio(filename: str) -> FileResponse:
    path = assistant_manager.audio_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Áudio do assistente não encontrado")
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

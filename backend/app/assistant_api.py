from __future__ import annotations

import asyncio
import threading
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .assistant import manager as assistant_manager
from .assistant_lab import analyze_audio as analyze_lab_audio
from .assistant_lab import analyze_text as analyze_lab_text
from .wake_word import manager as wake_word_manager


router = APIRouter()


class AssistantSettingsUpdate(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=30, ge=1, le=1440)
    voice_gender: Literal["female", "male"] = "female"
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    wake_enabled: bool = False


class TonhoLabTextRequest(BaseModel):
    camera_id: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=500)
    require_wake: bool = False
    speak: bool = False


def _warm_wake_model() -> None:
    try:
        wake_word_manager._ensure_model()
    except Exception as exc:
        wake_word_manager.error = str(exc)


@router.get("/api/assistant/status")
def assistant_status() -> dict:
    state = assistant_manager.state()
    state["wake_word"] = wake_word_manager.state()
    state["tonho_lab"] = {
        "available": wake_word_manager.available,
        "url": "/tonho-lab.html",
        "microphone_note": "Use localhost/HTTPS para o navegador liberar o microfone.",
    }
    return state


@router.get("/api/assistant/settings")
def assistant_settings() -> list[dict]:
    return wake_word_manager.enrich_settings(assistant_manager.list_settings())


@router.patch("/api/assistant/cameras/{camera_id}")
def update_assistant_camera(camera_id: int, payload: AssistantSettingsUpdate) -> dict:
    try:
        saved = assistant_manager.update_settings(
            camera_id,
            enabled=payload.enabled,
            interval_minutes=payload.interval_minutes,
            voice_gender=payload.voice_gender,
            timezone_name=payload.timezone,
        )
        wake_word_manager.update_setting(camera_id, payload.wake_enabled)
        if payload.enabled and payload.wake_enabled and wake_word_manager.available:
            threading.Thread(target=_warm_wake_model, name="poi-wake-model-warmup", daemon=True).start()
        return wake_word_manager.enrich_settings([saved])[0]
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


@router.post("/api/assistant/lab/text")
def tonho_lab_text(payload: TonhoLabTextRequest) -> dict:
    try:
        return analyze_lab_text(
            payload.camera_id,
            payload.text,
            require_wake=payload.require_wake,
            speak=payload.speak,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/assistant/lab/audio")
async def tonho_lab_audio(
    request: Request,
    camera_id: int,
    require_wake: bool = True,
    speak: bool = False,
) -> dict:
    payload = await request.body()
    try:
        return await asyncio.to_thread(
            analyze_lab_audio,
            camera_id,
            payload,
            require_wake=require_wake,
            speak=speak,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/assistant/audio/{filename}", include_in_schema=False)
def assistant_audio(filename: str) -> FileResponse:
    path = assistant_manager.audio_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Áudio do assistente não encontrado")
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

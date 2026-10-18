from __future__ import annotations

import threading
import time
from typing import Any

from . import wake_word as ww
from .config import (
    WAKE_COMMAND_WHISPER_MODEL,
    WAKE_FALLBACK_COOLDOWN_SECONDS,
    WAKE_FALLBACK_MAX_WORDS,
    WAKE_FALLBACK_MIN_RMS,
    WAKE_FALLBACK_STT_ENABLED,
    WAKE_MIN_RMS,
    WAKE_WHISPER_MODEL,
)


COMMAND_PROMPT = (
    "Assistente Tonho em português do Brasil. Exemplos de comandos: "
    "Oi, Tonho! Que horas são? Quem sou eu? Quem está aqui? "
    "Quem passou por aqui hoje? Quando uma pessoa passou por aqui? "
    "Quantas pessoas passaram hoje? Tem alguém desconhecido?"
)

_thread_local = threading.local()


def _conversation_is_open(manager: Any, camera_id: int) -> bool:
    until = float(getattr(manager, "_poi_conversation_until", {}).get(camera_id, 0.0) or 0.0)
    return until > time.monotonic()


def _merge_wake_and_command(fast: str, command: str) -> str:
    """Preserve a reliable wake hit while using the better command text."""
    fast = (fast or "").strip()
    command = (command or "").strip()
    if not command:
        return fast
    if ww.matches_wake_phrase(command):
        return command
    if ww.matches_wake_phrase(fast):
        return f"Oi, Tonho! {command}".strip()
    return command


def _eligible_for_wake_probe(fast: str, rms: float) -> bool:
    """Cheap gate before asking the stronger model to rescue a missed wake."""
    if not WAKE_FALLBACK_STT_ENABLED or rms < WAKE_FALLBACK_MIN_RMS:
        return False
    normalized = ww.normalize_phrase(fast)
    words = normalized.split()
    return 1 <= len(words) <= max(1, WAKE_FALLBACK_MAX_WORDS)


def _ensure_command_runtime(manager: Any) -> None:
    if not hasattr(manager, "_poi_command_model"):
        manager._poi_command_model = None
    if not hasattr(manager, "_poi_command_model_name"):
        manager._poi_command_model_name = None
    if not hasattr(manager, "_poi_last_fallback_probe"):
        manager._poi_last_fallback_probe = {}


def _ensure_command_model(manager: Any, model_name: str | None = None) -> Any:
    _ensure_command_runtime(manager)
    name = str(model_name or WAKE_COMMAND_WHISPER_MODEL).strip().lower()
    model = manager._ensure_model(name)
    manager._poi_command_model = model
    manager._poi_command_model_name = name
    return model


def _transcribe_base(
    manager: Any,
    audio: Any,
    *,
    command_context: bool,
    model_name: str | None = None,
) -> str:
    model = _ensure_command_model(manager, model_name)
    kwargs: dict[str, Any] = {
        "language": "pt",
        "beam_size": 3,
        "best_of": 3,
        "temperature": 0.0,
        "vad_filter": True,
        "condition_on_previous_text": False,
    }
    kwargs["initial_prompt"] = (
        COMMAND_PROMPT if command_context else "Português do Brasil. Transcrição literal."
    )
    with manager.model_lock:
        segments, _ = model.transcribe(audio, **kwargs)
        return " ".join(
            segment.text.strip() for segment in segments if segment.text.strip()
        ).strip()


def _transcribe_command(manager: Any, audio: Any, model_name: str | None = None) -> str:
    return _transcribe_base(
        manager,
        audio,
        command_context=True,
        model_name=model_name,
    )


def _can_probe_now(manager: Any, camera_id: int) -> bool:
    _ensure_command_runtime(manager)
    now = time.monotonic()
    previous = float(manager._poi_last_fallback_probe.get(camera_id, 0.0) or 0.0)
    if now - previous < max(0.0, WAKE_FALLBACK_COOLDOWN_SECONDS):
        return False
    manager._poi_last_fallback_probe[camera_id] = now
    return True


def install() -> None:
    """Use the selected fast model first and selected command model after wake."""
    cls = ww.WakeWordManager
    if getattr(cls, "_poi_dual_stt_patch", False):
        return

    original_transcribe = cls._transcribe
    original_process = cls._process_audio_window
    original_state = cls.state

    def transcribe_with_override(
        self: Any,
        audio: Any,
        model_name: str | None = None,
    ) -> str:
        override = getattr(_thread_local, "transcript_override", None)
        if override is not None:
            return str(override)
        return original_transcribe(self, audio, model_name)

    def process_with_dual_stt(self: Any, camera: dict[str, Any], audio: Any) -> None:
        camera_id = int(camera["id"])
        wake_model = str(camera.get("wake_model") or WAKE_WHISPER_MODEL).strip().lower()
        command_model = str(camera.get("command_model") or WAKE_COMMAND_WHISPER_MODEL).strip().lower()

        mute_until = float(
            getattr(self, "_poi_audio_mute_until", {}).get(camera_id, 0.0) or 0.0
        )
        if time.monotonic() < mute_until:
            return original_process(self, camera, audio)

        if audio is None or getattr(audio, "size", 0) == 0:
            return original_process(self, camera, audio)
        try:
            rms = float(ww.np.sqrt(ww.np.mean(ww.np.square(audio))))
            if rms < WAKE_MIN_RMS:
                return original_process(self, camera, audio)
        except Exception:
            rms = 0.0

        try:
            fast = original_transcribe(self, audio, wake_model)
        except Exception as exc:
            self._set_camera_state(
                camera_id,
                status="error",
                error=str(exc),
                wake_model=wake_model,
                command_model=command_model,
            )
            return

        if not fast:
            return

        wake_hit = ww.matches_wake_phrase(fast)
        conversation_open = _conversation_is_open(self, camera_id)
        chosen = fast
        route = wake_model
        command_text: str | None = None
        wake_probe_text: str | None = None
        rescued_wake = False

        if wake_hit or conversation_open:
            try:
                self._set_camera_state(
                    camera_id,
                    status="transcribing_command",
                    last_fast_transcript=fast,
                    wake_model=wake_model,
                    command_model=command_model,
                    error=None,
                )
                command_text = _transcribe_command(self, audio, command_model)
                chosen = _merge_wake_and_command(fast, command_text)
                route = f"{command_model}_command"
            except Exception as exc:
                self._set_camera_state(
                    camera_id,
                    command_model_error=str(exc),
                    last_fast_transcript=fast,
                    wake_model=wake_model,
                    command_model=command_model,
                )
                chosen = fast
                route = f"{wake_model}_fallback"
        elif _eligible_for_wake_probe(fast, rms) and _can_probe_now(self, camera_id):
            try:
                self._set_camera_state(
                    camera_id,
                    status="checking_wake",
                    last_fast_transcript=fast,
                    wake_model=wake_model,
                    command_model=command_model,
                )
                wake_probe_text = _transcribe_base(
                    self,
                    audio,
                    command_context=False,
                    model_name=command_model,
                )
                rescued_wake = ww.matches_wake_phrase(wake_probe_text)
                if rescued_wake:
                    chosen = wake_probe_text
                    command_text = wake_probe_text
                    route = f"{command_model}_wake_rescue"
                else:
                    route = f"{command_model}_wake_probe_miss"
            except Exception as exc:
                self._set_camera_state(camera_id, command_model_error=str(exc))
                route = f"{wake_model}_probe_error"

        state_updates: dict[str, Any] = {
            "last_fast_transcript": fast,
            "last_command_transcript": command_text,
            "last_wake_probe_transcript": wake_probe_text,
            "last_wake_probe_matched": rescued_wake,
            "last_stt_route": route,
            "wake_model": wake_model,
            "command_model": command_model,
        }
        if not (wake_hit or conversation_open or rescued_wake):
            state_updates.update(
                last_command=None,
                last_intent="none",
                last_route=route,
            )
        self._set_camera_state(camera_id, **state_updates)

        _thread_local.transcript_override = chosen
        try:
            return original_process(self, camera, audio)
        finally:
            _thread_local.transcript_override = None

    def state_with_dual_stt(self: Any) -> dict[str, Any]:
        data = original_state(self)
        _ensure_command_runtime(self)
        loaded = set(data.get("loaded_models") or [])
        data["wake_model"] = WAKE_WHISPER_MODEL
        data["command_model"] = WAKE_COMMAND_WHISPER_MODEL
        data["command_model_loaded"] = WAKE_COMMAND_WHISPER_MODEL in loaded
        data["dual_stt"] = True
        data["wake_fallback_enabled"] = WAKE_FALLBACK_STT_ENABLED
        data["wake_fallback_min_rms"] = WAKE_FALLBACK_MIN_RMS
        data["wake_fallback_max_words"] = WAKE_FALLBACK_MAX_WORDS
        data["hotfix"] = "4.7"
        return data

    cls._transcribe = transcribe_with_override
    cls._process_audio_window = process_with_dual_stt
    cls.state = state_with_dual_stt
    cls._poi_dual_stt_patch = True

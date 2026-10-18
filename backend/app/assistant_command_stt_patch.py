from __future__ import annotations

import threading
import time
from typing import Any

from . import wake_word as ww
from .config import WAKE_COMMAND_WHISPER_MODEL, WAKE_MIN_RMS


COMMAND_PROMPT = (
    "Assistente Tonho em português do Brasil. Exemplos de comandos: "
    "Oi, Tonho! Que horas são? Quem sou eu? Quem está aqui? "
    "Quem passou aqui hoje? Quando uma pessoa passou por aqui? "
    "Quantas pessoas passaram hoje? Tem alguém desconhecido?"
)

_thread_local = threading.local()


def _conversation_is_open(manager: Any, camera_id: int) -> bool:
    until = float(getattr(manager, "_poi_conversation_until", {}).get(camera_id, 0.0) or 0.0)
    return until > time.monotonic()


def _merge_wake_and_command(fast: str, command: str) -> str:
    """Preserve the reliable tiny wake hit while using the better command text."""
    fast = (fast or "").strip()
    command = (command or "").strip()
    if not command:
        return fast
    if ww.matches_wake_phrase(command):
        return command
    if ww.matches_wake_phrase(fast):
        return f"Oi, Tonho! {command}".strip()
    return command


def _ensure_command_runtime(manager: Any) -> None:
    if not hasattr(manager, "_poi_command_model"):
        manager._poi_command_model = None
    if not hasattr(manager, "_poi_command_model_lock"):
        manager._poi_command_model_lock = threading.Lock()


def _ensure_command_model(manager: Any) -> Any:
    _ensure_command_runtime(manager)
    if manager._poi_command_model is not None:
        return manager._poi_command_model
    if not ww.WAKE_RUNTIME_AVAILABLE:
        raise RuntimeError(ww.WAKE_RUNTIME_ERROR or "faster-whisper indisponível")
    with manager._poi_command_model_lock:
        if manager._poi_command_model is None:
            previous = manager.status
            manager.status = "loading_command_model"
            try:
                manager._poi_command_model = ww.WhisperModel(
                    WAKE_COMMAND_WHISPER_MODEL,
                    device="cpu",
                    compute_type="int8",
                )
            finally:
                if manager.status == "loading_command_model":
                    manager.status = previous if previous not in {"stopped", "error"} else "running"
    return manager._poi_command_model


def _transcribe_command(manager: Any, audio: Any) -> str:
    model = _ensure_command_model(manager)
    with manager._poi_command_model_lock:
        segments, _ = model.transcribe(
            audio,
            language="pt",
            beam_size=3,
            best_of=3,
            temperature=0.0,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=COMMAND_PROMPT,
        )
        return " ".join(
            segment.text.strip() for segment in segments if segment.text.strip()
        ).strip()


def install() -> None:
    """Use tiny for wake detection and a better model only for commands.

    The existing V4.5 conversation state machine remains authoritative. This
    patch only chooses which transcript it sees. A thread-local override avoids
    races between camera workers while preserving the existing method.
    """
    cls = ww.WakeWordManager
    if getattr(cls, "_poi_dual_stt_patch", False):
        return

    original_transcribe = cls._transcribe
    original_process = cls._process_audio_window
    original_state = cls.state

    def transcribe_with_override(self: Any, audio: Any) -> str:
        override = getattr(_thread_local, "transcript_override", None)
        if override is not None:
            return str(override)
        return original_transcribe(self, audio)

    def process_with_dual_stt(self: Any, camera: dict[str, Any], audio: Any) -> None:
        camera_id = int(camera["id"])

        # Avoid invoking Whisper on silent windows. The original state machine
        # uses the same threshold; doing it here keeps the always-on tiny path
        # as cheap as V4.4.
        if audio is None or getattr(audio, "size", 0) == 0:
            return original_process(self, camera, audio)
        try:
            rms = float(ww.np.sqrt(ww.np.mean(ww.np.square(audio))))
            if rms < WAKE_MIN_RMS:
                return original_process(self, camera, audio)
        except Exception:
            pass

        try:
            fast = original_transcribe(self, audio)
        except Exception:
            return original_process(self, camera, audio)

        if not fast:
            return

        wake_hit = ww.matches_wake_phrase(fast)
        conversation_open = _conversation_is_open(self, camera_id)
        chosen = fast
        route = "tiny"
        command_text = None

        if wake_hit or conversation_open:
            try:
                self._set_camera_state(
                    camera_id,
                    status="transcribing_command",
                    last_fast_transcript=fast,
                    command_model=WAKE_COMMAND_WHISPER_MODEL,
                )
                command_text = _transcribe_command(self, audio)
                chosen = _merge_wake_and_command(fast, command_text)
                route = f"{WAKE_COMMAND_WHISPER_MODEL}_command"
            except Exception as exc:
                # Never make a model download/load failure kill wake-word mode.
                self._set_camera_state(
                    camera_id,
                    command_model_error=str(exc),
                    last_fast_transcript=fast,
                )
                chosen = fast
                route = "tiny_fallback"

        self._set_camera_state(
            camera_id,
            last_fast_transcript=fast,
            last_command_transcript=command_text,
            last_stt_route=route,
        )

        _thread_local.transcript_override = chosen
        try:
            return original_process(self, camera, audio)
        finally:
            _thread_local.transcript_override = None

    def state_with_dual_stt(self: Any) -> dict[str, Any]:
        data = original_state(self)
        _ensure_command_runtime(self)
        data["wake_model"] = data.get("model")
        data["command_model"] = WAKE_COMMAND_WHISPER_MODEL
        data["command_model_loaded"] = self._poi_command_model is not None
        data["dual_stt"] = True
        data["hotfix"] = "4.5.3"
        return data

    cls._transcribe = transcribe_with_override
    cls._process_audio_window = process_with_dual_stt
    cls.state = state_with_dual_stt
    cls._poi_dual_stt_patch = True

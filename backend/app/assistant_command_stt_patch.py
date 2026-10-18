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
)


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
    """Cheap gate before asking the base model to rescue a missed wake word.

    The gate intentionally accepts short, clear speech even when tiny mangles the
    words completely (for example "Oito em André..." for "Oi, Tonho..."). The
    stronger model still has to independently hear the actual wake phrase, so a
    tiny transcript alone can never activate Tonho.
    """
    if not WAKE_FALLBACK_STT_ENABLED or rms < WAKE_FALLBACK_MIN_RMS:
        return False
    normalized = ww.normalize_phrase(fast)
    words = normalized.split()
    return 1 <= len(words) <= max(1, WAKE_FALLBACK_MAX_WORDS)


def _ensure_command_runtime(manager: Any) -> None:
    if not hasattr(manager, "_poi_command_model"):
        manager._poi_command_model = None
    if not hasattr(manager, "_poi_command_model_lock"):
        manager._poi_command_model_lock = threading.Lock()
    if not hasattr(manager, "_poi_last_fallback_probe"):
        manager._poi_last_fallback_probe = {}


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


def _transcribe_base(manager: Any, audio: Any, *, command_context: bool) -> str:
    model = _ensure_command_model(manager)
    kwargs: dict[str, Any] = {
        "language": "pt",
        "beam_size": 3,
        "best_of": 3,
        "temperature": 0.0,
        "vad_filter": True,
        "condition_on_previous_text": False,
    }
    # Full command context is helpful after wake. During a rescue probe we keep
    # the prompt neutral so it cannot bias unrelated speech toward "Oi, Tonho".
    kwargs["initial_prompt"] = COMMAND_PROMPT if command_context else "Português do Brasil. Transcrição literal."
    with manager._poi_command_model_lock:
        segments, _ = model.transcribe(audio, **kwargs)
        return " ".join(
            segment.text.strip() for segment in segments if segment.text.strip()
        ).strip()


def _transcribe_command(manager: Any, audio: Any) -> str:
    return _transcribe_base(manager, audio, command_context=True)


def _can_probe_now(manager: Any, camera_id: int) -> bool:
    _ensure_command_runtime(manager)
    now = time.monotonic()
    previous = float(manager._poi_last_fallback_probe.get(camera_id, 0.0) or 0.0)
    if now - previous < max(0.0, WAKE_FALLBACK_COOLDOWN_SECONDS):
        return False
    manager._poi_last_fallback_probe[camera_id] = now
    return True


def install() -> None:
    """Use tiny first, but never make it a single point of failure.

    Tiny remains the cheap continuous listener. The base model handles commands
    after activation and may also perform a throttled rescue probe on short,
    clear speech when tiny fails to hear the wake phrase.
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

        # If the conversation state machine is deliberately ignoring the tail of
        # Tonho's own TTS, avoid spending CPU on either Whisper model.
        mute_until = float(getattr(self, "_poi_audio_mute_until", {}).get(camera_id, 0.0) or 0.0)
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
            fast = original_transcribe(self, audio)
        except Exception:
            return original_process(self, camera, audio)

        if not fast:
            return

        wake_hit = ww.matches_wake_phrase(fast)
        conversation_open = _conversation_is_open(self, camera_id)
        chosen = fast
        route = "tiny"
        command_text: str | None = None
        wake_probe_text: str | None = None
        rescued_wake = False

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
                self._set_camera_state(
                    camera_id,
                    command_model_error=str(exc),
                    last_fast_transcript=fast,
                )
                chosen = fast
                route = "tiny_fallback"
        elif _eligible_for_wake_probe(fast, rms) and _can_probe_now(self, camera_id):
            try:
                self._set_camera_state(
                    camera_id,
                    status="checking_wake",
                    last_fast_transcript=fast,
                    command_model=WAKE_COMMAND_WHISPER_MODEL,
                )
                wake_probe_text = _transcribe_base(self, audio, command_context=False)
                rescued_wake = ww.matches_wake_phrase(wake_probe_text)
                if rescued_wake:
                    # The base transcript is already the best transcription of
                    # this exact window, so let the normal conversation state
                    # machine process it as if tiny had heard the wake word.
                    chosen = wake_probe_text
                    command_text = wake_probe_text
                    route = f"{WAKE_COMMAND_WHISPER_MODEL}_wake_rescue"
                else:
                    route = f"{WAKE_COMMAND_WHISPER_MODEL}_wake_probe_miss"
            except Exception as exc:
                self._set_camera_state(camera_id, command_model_error=str(exc))
                route = "tiny_probe_error"

        # Clear stale command diagnostics when this window did not activate or
        # continue a conversation. This makes the status JSON describe the most
        # recent attempt instead of an older successful question.
        state_updates: dict[str, Any] = {
            "last_fast_transcript": fast,
            "last_command_transcript": command_text,
            "last_wake_probe_transcript": wake_probe_text,
            "last_wake_probe_matched": rescued_wake,
            "last_stt_route": route,
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
        data["wake_model"] = data.get("model")
        data["command_model"] = WAKE_COMMAND_WHISPER_MODEL
        data["command_model_loaded"] = self._poi_command_model is not None
        data["dual_stt"] = True
        data["wake_fallback_enabled"] = WAKE_FALLBACK_STT_ENABLED
        data["wake_fallback_min_rms"] = WAKE_FALLBACK_MIN_RMS
        data["wake_fallback_max_words"] = WAKE_FALLBACK_MAX_WORDS
        data["hotfix"] = "4.5.4"
        return data

    cls._transcribe = transcribe_with_override
    cls._process_audio_window = process_with_dual_stt
    cls.state = state_with_dual_stt
    cls._poi_dual_stt_patch = True

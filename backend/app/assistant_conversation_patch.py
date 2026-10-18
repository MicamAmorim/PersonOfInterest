from __future__ import annotations

import difflib
import time
from typing import Any

from .assistant import manager as assistant_manager
from .assistant_tools import answer_command
from .config import (
    WAKE_AFTER_SPEECH_MUTE_SECONDS,
    WAKE_CONVERSATION_SECONDS,
    WAKE_FOLLOWUP_GUARD_SECONDS,
    WAKE_MIN_RMS,
    WAKE_RESPONSE_COOLDOWN_SECONDS,
)
from .db import connection, utc_now
from . import wake_word as ww


def _ensure_conversation_state(manager: Any) -> None:
    if not hasattr(manager, "_poi_conversation_until"):
        manager._poi_conversation_until = {}
    if not hasattr(manager, "_poi_conversation_ready_at"):
        manager._poi_conversation_ready_at = {}
    if not hasattr(manager, "_poi_audio_mute_until"):
        manager._poi_audio_mute_until = {}


def _timezone_for(camera_id: int) -> str:
    try:
        with connection() as conn:
            row = conn.execute(
                "SELECT timezone FROM camera_assistant_settings WHERE camera_id = ?",
                (camera_id,),
            ).fetchone()
        return str(row["timezone"] or "UTC") if row else "UTC"
    except Exception:
        return "UTC"


def _extract_command_after_wake(text: str) -> str:
    """Return words spoken after a tolerant 'Oi, Tonho' wake phrase."""
    normalized = ww.normalize_phrase(text)
    words = normalized.split()
    accepted = {"tonho", "tonio", "toni", "tony", "antonio"}
    for index, word in enumerate(words):
        if word != "oi":
            continue
        for offset in (1, 2):
            pos = index + offset
            if pos >= len(words):
                continue
            candidate = words[pos]
            if candidate in accepted or difflib.SequenceMatcher(None, candidate, "tonho").ratio() >= 0.76:
                return " ".join(words[pos + 1:]).strip()
    target = ww.normalize_phrase(ww.WAKE_PHRASE)
    if target and target in normalized:
        return normalized.split(target, 1)[1].strip()
    return ""


def _close_conversation(manager: Any, camera_id: int) -> None:
    _ensure_conversation_state(manager)
    manager._poi_conversation_until[camera_id] = 0.0
    manager._poi_conversation_ready_at[camera_id] = 0.0


def _set_mute(manager: Any, camera_id: int, seconds: float | None = None) -> float:
    _ensure_conversation_state(manager)
    duration = WAKE_AFTER_SPEECH_MUTE_SECONDS if seconds is None else seconds
    mute_until = time.monotonic() + max(0.0, duration)
    manager._poi_audio_mute_until[camera_id] = mute_until
    return mute_until


def _looks_like_last_tts(manager: Any, camera_id: int, transcript: str) -> bool:
    """Ignore likely speaker echo without muting the user's follow-up for seconds."""
    heard = ww.normalize_phrase(transcript)
    if len(heard) < 3:
        return False
    try:
        with manager.lock:
            state = dict(manager._camera_state.get(camera_id) or {})
    except Exception:
        state = dict(getattr(manager, "_camera_state", {}).get(camera_id) or {})
    spoken = ww.normalize_phrase(str(state.get("last_response") or ""))
    if len(spoken) < 3:
        return False
    if heard == spoken:
        return True
    if len(heard) >= 7 and (heard in spoken or spoken in heard):
        return True
    return difflib.SequenceMatcher(None, heard, spoken).ratio() >= 0.72


def _record_last(
    manager: Any,
    camera: dict[str, Any],
    transcript: str,
    response: str,
    certainty: str | None,
    person_id: int | None,
    *,
    intent: str,
    follow_up: bool,
) -> None:
    manager.last_wake = {
        "camera_id": int(camera["id"]),
        "camera_name": camera.get("name"),
        "transcript": transcript,
        "response": response,
        "certainty": certainty,
        "person_id": person_id,
        "intent": intent,
        "follow_up": follow_up,
        "created_at": utc_now(),
    }


def _speak_answer(
    manager: Any,
    camera: dict[str, Any],
    transcript: str,
    response: str,
    certainty: str | None,
    person_id: int | None,
    *,
    intent: str,
    follow_up: bool,
    open_conversation: bool,
) -> None:
    camera_id = int(camera["id"])
    voice_gender = str(camera.get("voice_gender") or "female")
    manager._set_camera_state(
        camera_id,
        status="responding",
        last_transcript=transcript,
        conversation_open=False,
    )
    try:
        assistant_manager.speak(camera_id, response, voice_gender=voice_gender)
        manager._last_trigger_monotonic[camera_id] = time.monotonic()

        # Final answers keep the conservative half-duplex guard. The short
        # "Pode falar" prompt uses a much smaller guard and an echo detector,
        # otherwise a natural immediate follow-up is discarded.
        mute_seconds = WAKE_FOLLOWUP_GUARD_SECONDS if open_conversation else WAKE_AFTER_SPEECH_MUTE_SECONDS
        mute_until = _set_mute(manager, camera_id, mute_seconds)
        if open_conversation:
            ready_at = mute_until
            manager._poi_conversation_ready_at[camera_id] = ready_at
            manager._poi_conversation_until[camera_id] = ready_at + max(1.0, WAKE_CONVERSATION_SECONDS)
            status = "waiting_command"
            conversation_open = True
        else:
            _close_conversation(manager, camera_id)
            status = "listening"
            conversation_open = False
        _record_last(
            manager,
            camera,
            transcript,
            response,
            certainty,
            person_id,
            intent=intent,
            follow_up=follow_up,
        )
        manager._log(camera_id, transcript, True, response, certainty, person_id)
        manager._set_camera_state(
            camera_id,
            status=status,
            last_response=response,
            last_intent=intent,
            conversation_open=conversation_open,
            conversation_seconds=WAKE_CONVERSATION_SECONDS if conversation_open else 0,
            error=None,
        )
    except Exception as exc:
        _close_conversation(manager, camera_id)
        manager._log(camera_id, transcript, True, None, certainty, person_id)
        manager._set_camera_state(camera_id, status="error", conversation_open=False, error=str(exc))


def _process_audio_window(self: Any, camera: dict[str, Any], audio: Any) -> None:
    _ensure_conversation_state(self)
    camera_id = int(camera["id"])
    now_mono = time.monotonic()

    if now_mono < float(self._poi_audio_mute_until.get(camera_id, 0.0)):
        return
    if audio.size == 0:
        return
    rms = float(ww.np.sqrt(ww.np.mean(ww.np.square(audio))))
    if rms < WAKE_MIN_RMS:
        return

    transcript = self._transcribe(audio)
    if not transcript:
        return

    now_mono = time.monotonic()
    conversation_until = float(self._poi_conversation_until.get(camera_id, 0.0))
    conversation_ready = float(self._poi_conversation_ready_at.get(camera_id, 0.0))
    if conversation_until and now_mono > conversation_until:
        _close_conversation(self, camera_id)
        conversation_until = 0.0
        self._set_camera_state(camera_id, status="listening", conversation_open=False)

    matched = ww.matches_wake_phrase(transcript)
    self._set_camera_state(
        camera_id,
        last_transcript=transcript,
        last_rms=round(rms, 5),
    )

    if matched:
        last = float(self._last_trigger_monotonic.get(camera_id, 0.0))
        if now_mono - last < WAKE_RESPONSE_COOLDOWN_SECONDS:
            return
        self._last_trigger_monotonic[camera_id] = now_mono
        command_text = _extract_command_after_wake(transcript)
        if command_text:
            answer = answer_command(camera_id, command_text, _timezone_for(camera_id))
            _speak_answer(
                self,
                camera,
                transcript,
                answer.text,
                answer.certainty,
                answer.person_id,
                intent=answer.intent,
                follow_up=False,
                open_conversation=False,
            )
            return

        hello, certainty, person_id = self._response_for(camera_id)
        response = f"{hello} Pode falar."
        _speak_answer(
            self,
            camera,
            transcript,
            response,
            certainty,
            person_id,
            intent="wake",
            follow_up=False,
            open_conversation=True,
        )
        return

    if conversation_until and now_mono >= conversation_ready and now_mono <= conversation_until:
        # Speaker echo can arrive after go2rtc has already returned. Ignore that
        # echo but keep the conversation open so the next real utterance is heard.
        if _looks_like_last_tts(self, camera_id, transcript):
            self._set_camera_state(
                camera_id,
                status="waiting_command",
                conversation_open=True,
                last_echo=transcript,
            )
            return

        answer = answer_command(camera_id, transcript, _timezone_for(camera_id))
        _close_conversation(self, camera_id)
        _speak_answer(
            self,
            camera,
            transcript,
            answer.text,
            answer.certainty,
            answer.person_id,
            intent=answer.intent,
            follow_up=True,
            open_conversation=False,
        )
        return

    self._log(camera_id, transcript, False, None, None, None)
    self._set_camera_state(camera_id, status="listening", conversation_open=False)


def install() -> None:
    cls = ww.WakeWordManager
    if getattr(cls, "_poi_conversation_patch", False):
        return

    original_state = cls.state

    def state_with_conversation(self: Any) -> dict[str, Any]:
        data = original_state(self)
        data["conversation_seconds"] = WAKE_CONVERSATION_SECONDS
        data["followup_guard_seconds"] = WAKE_FOLLOWUP_GUARD_SECONDS
        data["simple_commands"] = [
            "Quem sou eu?",
            "Quem está aqui?",
            "Quem passou aqui hoje?",
            "Quando <nome> passou por aqui?",
            "Quantas pessoas passaram hoje?",
            "Tem alguém desconhecido?",
            "Que horas são?",
        ]
        return data

    cls._process_audio_window = _process_audio_window
    cls.state = state_with_conversation
    cls._poi_conversation_patch = True

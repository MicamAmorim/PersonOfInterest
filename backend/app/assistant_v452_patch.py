from __future__ import annotations

import difflib
import time
from typing import Any

from . import assistant_conversation_patch as conv
from . import wake_word as ww
from .assistant_tools import answer_command, normalize_text
from .config import WAKE_CONVERSATION_SECONDS, WAKE_MIN_RMS


# V4.5.2 hotfix constants. The camera can still echo after TTS, but filtering the
# last response is preferable to making the listener deaf for several seconds.
FINAL_GUARD_SECONDS = 0.35
FOLLOWUP_GUARD_SECONDS = 0.25
WAKE_COOLDOWN_SECONDS = 0.35


def looks_like_time_request(text: str) -> bool:
    """Recognize current-time questions directly from raw Whisper text.

    This intentionally runs before generic command parsing. Tiny Whisper can
    render 'horas' as 'oras', 'horras', 'hora', etc.; requiring an exact phrase
    made a basic command unreliable on real camera audio.
    """
    q = normalize_text(text)
    if not q:
        return False
    tokens = q.split()
    targets = ("hora", "horas", "horario")
    has_time_word = False
    for token in tokens:
        if token.startswith("hora"):
            has_time_word = True
            break
        if len(token) >= 3 and max(difflib.SequenceMatcher(None, token, target).ratio() for target in targets) >= 0.68:
            has_time_word = True
            break
    if not has_time_word:
        return False

    # Direct requests are intentionally permissive inside the Tonho command
    # channel. These cues cover both full and split-window transcriptions.
    cues = {"que", "qual", "agora", "sao", "e", "eh", "diz", "diga", "fala", "fale", "me"}
    if len(tokens) <= 3 or cues.intersection(tokens):
        return True
    return any(fragment in q for fragment in ("que hora", "qual hora", "hora agora", "horario agora"))


def _ensure_v452_state(manager: Any) -> None:
    conv._ensure_conversation_state(manager)
    if not hasattr(manager, "_poi_pending_command"):
        manager._poi_pending_command = {}
    if not hasattr(manager, "_poi_pending_attempts"):
        manager._poi_pending_attempts = {}


def _clear_pending(manager: Any, camera_id: int) -> None:
    _ensure_v452_state(manager)
    manager._poi_pending_command.pop(camera_id, None)
    manager._poi_pending_attempts.pop(camera_id, None)


def _open_silent_command_window(manager: Any, camera_id: int, command_text: str, transcript: str) -> None:
    """Wait for the next audio window instead of answering an incomplete chunk."""
    _ensure_v452_state(manager)
    manager._poi_pending_command[camera_id] = command_text.strip()
    manager._poi_pending_attempts[camera_id] = int(manager._poi_pending_attempts.get(camera_id, 0)) + 1
    now = time.monotonic()
    manager._poi_conversation_ready_at[camera_id] = now
    manager._poi_conversation_until[camera_id] = now + max(2.0, WAKE_CONVERSATION_SECONDS)
    manager._poi_audio_mute_until[camera_id] = 0.0
    manager._set_camera_state(
        camera_id,
        status="waiting_command",
        conversation_open=True,
        last_transcript=transcript,
        last_command=command_text,
        last_intent="pending",
        last_route="partial_wake_command",
        error=None,
    )


def _canonical_time_answer(camera_id: int, timezone_name: str):
    # Canonical text bypasses any noisy variation once the raw transcript has
    # already been recognized as a time request by looks_like_time_request().
    return answer_command(camera_id, "que horas sao", timezone_name)


def _speak(
    manager: Any,
    camera: dict[str, Any],
    transcript: str,
    answer: Any,
    *,
    follow_up: bool,
    reopen: bool,
    route: str,
    command_text: str,
) -> None:
    camera_id = int(camera["id"])
    _clear_pending(manager, camera_id)
    manager._set_camera_state(
        camera_id,
        last_command=command_text,
        last_intent=answer.intent,
        last_route=route,
    )
    conv._speak_answer(
        manager,
        camera,
        transcript,
        answer.text,
        answer.certainty,
        answer.person_id,
        intent=answer.intent,
        follow_up=follow_up,
        open_conversation=reopen,
    )


def _process_audio_window(self: Any, camera: dict[str, Any], audio: Any) -> None:
    _ensure_v452_state(self)
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
        conv._close_conversation(self, camera_id)
        _clear_pending(self, camera_id)
        conversation_until = 0.0
        self._set_camera_state(camera_id, status="listening", conversation_open=False)

    matched = ww.matches_wake_phrase(transcript)
    self._set_camera_state(camera_id, last_transcript=transcript, last_rms=round(rms, 5))
    timezone_name = conv._timezone_for(camera_id)

    if matched:
        # A fresh explicit wake phrase always recovers the listener, even if a
        # previous command left a conversation window open.
        active_conversation = bool(conversation_until and now_mono <= conversation_until)
        last = float(self._last_trigger_monotonic.get(camera_id, 0.0))
        if not active_conversation and now_mono - last < WAKE_COOLDOWN_SECONDS:
            return
        self._last_trigger_monotonic[camera_id] = now_mono
        self._poi_audio_mute_until[camera_id] = 0.0
        _clear_pending(self, camera_id)

        command_text = conv._extract_command_after_wake(transcript)

        # First inspect the complete raw transcription. This is the path that
        # guarantees 'Oi, Tonho, que horas são?' works even if extraction or a
        # Whisper spelling is imperfect.
        if looks_like_time_request(transcript):
            answer = _canonical_time_answer(camera_id, timezone_name)
            _speak(
                self, camera, transcript, answer,
                follow_up=False, reopen=False, route="raw_time_fast_path",
                command_text=command_text or transcript,
            )
            return

        if command_text:
            answer = answer_command(camera_id, command_text, timezone_name)
            if answer.intent not in {"unknown", "empty"}:
                _speak(
                    self, camera, transcript, answer,
                    follow_up=False, reopen=False, route="wake_command",
                    command_text=command_text,
                )
                return

            # A fixed 4 s Whisper window can split 'Oi Tonho, que...' from the
            # rest of the question. Do not interrupt with an 'I don't know'
            # response; retain the partial command and wait for the next window.
            _open_silent_command_window(self, camera_id, command_text, transcript)
            return

        hello, certainty, person_id = self._response_for(camera_id)
        response = f"{hello} Pode falar."
        self._set_camera_state(camera_id, last_command="", last_intent="wake", last_route="wake_only")
        conv._speak_answer(
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
        if conv._looks_like_last_tts(self, camera_id, transcript):
            self._set_camera_state(
                camera_id,
                status="waiting_command",
                conversation_open=True,
                last_echo=transcript,
                last_route="tts_echo_ignored",
            )
            return

        pending = str(self._poi_pending_command.get(camera_id) or "").strip()
        combined = " ".join(part for part in (pending, transcript) if part).strip()

        if looks_like_time_request(combined):
            answer = _canonical_time_answer(camera_id, timezone_name)
            conv._close_conversation(self, camera_id)
            _speak(
                self, camera, transcript, answer,
                follow_up=True, reopen=False, route="combined_time_fast_path",
                command_text=combined,
            )
            return

        answer = answer_command(camera_id, combined or transcript, timezone_name)
        if answer.intent in {"unknown", "empty"}:
            attempts = int(self._poi_pending_attempts.get(camera_id, 0))
            if pending and attempts < 2:
                _open_silent_command_window(self, camera_id, combined, transcript)
                return

            # A misunderstood command must never leave Tonho apparently dead.
            # Give concise feedback and reopen the command window.
            answer.text = "Não entendi. Pode repetir?"
            answer.intent = "unknown"
            conv._close_conversation(self, camera_id)
            _speak(
                self, camera, transcript, answer,
                follow_up=True, reopen=True, route="unknown_retry",
                command_text=combined or transcript,
            )
            return

        conv._close_conversation(self, camera_id)
        _speak(
            self, camera, transcript, answer,
            follow_up=True, reopen=False, route="followup_command",
            command_text=combined or transcript,
        )
        return

    self._log(camera_id, transcript, False, None, None, None)
    self._set_camera_state(camera_id, status="listening", conversation_open=False)


def install() -> None:
    cls = ww.WakeWordManager
    if getattr(cls, "_poi_v452_patch", False):
        return

    # conv._speak_answer reads these module globals at runtime. Keep guards short
    # and let echo matching do the heavy lifting instead of muting the listener.
    conv.WAKE_AFTER_SPEECH_MUTE_SECONDS = FINAL_GUARD_SECONDS
    conv.WAKE_FOLLOWUP_GUARD_SECONDS = FOLLOWUP_GUARD_SECONDS
    conv.WAKE_RESPONSE_COOLDOWN_SECONDS = WAKE_COOLDOWN_SECONDS

    original_state = cls.state

    def state_with_v452(self: Any) -> dict[str, Any]:
        data = original_state(self)
        data["hotfix"] = "4.5.2"
        data["final_guard_seconds"] = FINAL_GUARD_SECONDS
        data["followup_guard_seconds"] = FOLLOWUP_GUARD_SECONDS
        return data

    cls._process_audio_window = _process_audio_window
    cls.state = state_with_v452
    cls._poi_v452_patch = True

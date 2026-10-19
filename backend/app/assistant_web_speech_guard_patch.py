from __future__ import annotations

import re
import socket
import time
import urllib.error
from typing import Any

from . import assistant_tools as tools
from . import assistant_web_search_patch as web
from .assistant import manager as assistant_manager


WEB_PREFACE_MIN_GAP_SECONDS = 2.25


def _preface_for(text: str) -> str | None:
    try:
        intent, _ = tools.detect_intent(text, tools._person_names())
    except Exception:
        return None
    return web.WEB_SEARCH_PREFACE if intent == "web_search" else None


def _clean_runtime_query(query: str) -> str:
    value = web._cleanup_spoken_query(str(query or ""))
    # Whisper commonly writes the colloquial "pra mim", while the original
    # cleaner only knew the formal "para mim".
    value = re.sub(
        r"^\s*(?:pra|prá|para)\s+mim\b\s*[,;:\-]?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"^\s*(?:por\s+favor)\b\s*[,;:\-]?\s*", "", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip(" .?!:;,-")


def _pure_web_answer(camera_id: int, text: str, timezone_name: str | None = None) -> Any:
    intent, argument = tools.detect_intent(text, tools._person_names())
    if intent != "web_search":
        raise LookupError("not_web_search")

    query = _clean_runtime_query(str(argument or ""))
    if not query:
        return tools.CommandAnswer("Diga o que você quer que eu pesquise.", intent, "unknown")
    try:
        results, provider = web._search(query)
        return tools.CommandAnswer(web._summarize(query, results), intent, f"web:{provider}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout) as exc:
        return tools.CommandAnswer(
            f"Não consegui acessar a pesquisa na internet agora. {type(exc).__name__}.",
            intent,
            "web:error",
        )
    except Exception:
        return tools.CommandAnswer("Não consegui concluir essa pesquisa na internet.", intent, "web:error")


def _ensure_preface_state() -> dict[int, float]:
    from . import wake_word as ww

    if not hasattr(ww.manager, "_poi_web_preface_at"):
        ww.manager._poi_web_preface_at = {}
    return ww.manager._poi_web_preface_at


def _speak_preface(camera_id: int, text: str) -> bool:
    preface = _preface_for(text)
    if not preface:
        return False
    try:
        settings = assistant_manager.settings_for(camera_id)
        assistant_manager.speak(
            camera_id,
            preface,
            voice_gender=str(settings.get("voice_gender") or "female"),
        )
        _ensure_preface_state()[camera_id] = time.monotonic()
        return True
    except Exception:
        # A falha do preâmbulo não deve impedir a pesquisa nem a resposta final.
        return False


def _wait_for_preface_gap(camera_id: int) -> None:
    started = _ensure_preface_state().get(camera_id)
    if started is None:
        return
    remaining = WEB_PREFACE_MIN_GAP_SECONDS - (time.monotonic() - float(started))
    if remaining > 0:
        time.sleep(remaining)


def install() -> None:
    if getattr(tools, "_poi_web_speech_guard_installed", False):
        return

    side_effecting_answer = tools.answer_command

    def pure_answer(camera_id: int, text: str, timezone_name: str | None = None) -> Any:
        intent, _ = tools.detect_intent(text, tools._person_names())
        if intent == "web_search":
            return _pure_web_answer(camera_id, text, timezone_name)
        return side_effecting_answer(camera_id, text, timezone_name)

    # Generic command evaluation must never emit audio by itself. This is what
    # Tonho Lab and any future API/tool callers receive.
    tools.answer_command = pure_answer
    tools.command_preface = _preface_for  # type: ignore[attr-defined]

    # The live wake-word path is explicitly authorized to speak. Keep the
    # requested two-stage UX there: preface first, then the final answer.
    from . import assistant_conversation_patch as conversation

    def live_answer(camera_id: int, text: str, timezone_name: str | None = None) -> Any:
        _speak_preface(camera_id, text)
        return pure_answer(camera_id, text, timezone_name)

    conversation.answer_command = live_answer

    # V4.5.2 imported answer_command by value before the web-search patch was
    # installed. The dual-STT live camera path ultimately calls this module, so
    # refresh that captured reference too. Without this line Tonho Lab can search
    # while the real camera still routes the same phrase to the old command set.
    from . import assistant_v452_patch as v452

    v452.answer_command = live_answer

    # Keep two talkback files from colliding when the web result returns very
    # quickly. go2rtc acknowledges playback before the camera necessarily
    # finishes speaking the preface.
    original_speak_answer = conversation._speak_answer

    def speak_answer_with_web_gap(
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
        if intent == "web_search":
            _wait_for_preface_gap(camera_id)
        original_speak_answer(
            manager,
            camera,
            transcript,
            response,
            certainty,
            person_id,
            intent=intent,
            follow_up=follow_up,
            open_conversation=open_conversation,
        )

    conversation._speak_answer = speak_answer_with_web_gap
    tools._poi_web_speech_guard_installed = True

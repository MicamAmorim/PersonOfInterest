from __future__ import annotations

import socket
import urllib.error
from typing import Any

from . import assistant_tools as tools
from . import assistant_web_search_patch as web
from .assistant import manager as assistant_manager


def _preface_for(text: str) -> str | None:
    try:
        intent, _ = tools.detect_intent(text, tools._person_names())
    except Exception:
        return None
    return web.WEB_SEARCH_PREFACE if intent == "web_search" else None


def _pure_web_answer(camera_id: int, text: str, timezone_name: str | None = None) -> Any:
    intent, argument = tools.detect_intent(text, tools._person_names())
    if intent != "web_search":
        raise LookupError("not_web_search")

    query = str(argument or "").strip()
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


def _speak_preface(camera_id: int, text: str) -> None:
    preface = _preface_for(text)
    if not preface:
        return
    try:
        settings = assistant_manager.settings_for(camera_id)
        assistant_manager.speak(
            camera_id,
            preface,
            voice_gender=str(settings.get("voice_gender") or "female"),
        )
    except Exception:
        # A falha do preâmbulo não deve impedir a pesquisa nem a resposta final.
        return


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
    tools._poi_web_speech_guard_installed = True

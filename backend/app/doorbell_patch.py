from __future__ import annotations

from typing import Any

from . import assistant_tools as tools
from .doorbell import manager as doorbell_manager


def _looks_like_arrival_notice(text: str) -> bool:
    q = tools.normalize_text(text)
    if not q:
        return False
    tokens = set(q.split())
    has_notice = any(token.startswith("avis") for token in tokens)
    if not has_notice:
        return False
    first_person = bool({"eu", "mim", "estou", "to", "aqui"}.intersection(tokens))
    arrived = any(token.startswith("cheg") for token in tokens)
    at_door = "porta" in tokens and (first_person or arrived)
    return at_door or (arrived and (first_person or "que" in tokens))


def install() -> None:
    if getattr(tools, "_poi_doorbell_patch_installed", False):
        return

    # Register the additive API under the V3/V4 router that main.py already
    # exposes. This avoids changing the central app/router lifecycle.
    from . import api_v34
    from .doorbell_api import router as doorbell_router

    if not getattr(api_v34.router, "_poi_doorbell_routes", False):
        api_v34.router.include_router(doorbell_router)
        api_v34.router._poi_doorbell_routes = True  # type: ignore[attr-defined]

    # Extend intent detection while preserving every existing Tonho command.
    original_detect = tools.detect_intent

    def detect_with_arrival(text: str, person_names: list[str] | None = None) -> tuple[str, str | None]:
        if _looks_like_arrival_notice(text):
            return "arrival_notify", None
        return original_detect(text, person_names)

    tools.detect_intent = detect_with_arrival

    # Generic command evaluation (Tonho Lab/API) remains side-effect free.
    # Only the real wake-word path below is allowed to broadcast a Push.
    previous_pure_answer = tools.answer_command

    def pure_answer(camera_id: int, text: str, timezone_name: str | None = None) -> Any:
        intent, _ = tools.detect_intent(text, tools._person_names())
        if intent == "arrival_notify":
            return tools.CommandAnswer(
                "Esse aviso é enviado quando você chama o Tonho pela câmera.",
                intent,
                "system",
            )
        return previous_pure_answer(camera_id, text, timezone_name)

    tools.answer_command = pure_answer

    from . import assistant_conversation_patch as conversation
    from . import assistant_v452_patch as v452

    previous_live_answer = conversation.answer_command

    def live_answer(camera_id: int, text: str, timezone_name: str | None = None) -> Any:
        intent, _ = tools.detect_intent(text, tools._person_names())
        if intent != "arrival_notify":
            return previous_live_answer(camera_id, text, timezone_name)
        result = doorbell_manager.queue_arrival_push(camera_id)
        if not result.get("subscriptions"):
            return tools.CommandAnswer(
                "Não há nenhum aparelho com notificações ativas para eu avisar.",
                intent,
                "system",
            )
        person_name = result.get("person_name")
        if person_name:
            text_out = f"Certo, vou avisar que {person_name} chegou."
            certainty = "known"
        else:
            text_out = "Certo, vou avisar que alguém chegou."
            certainty = "unknown"
        return tools.CommandAnswer(
            text_out,
            intent,
            certainty,
            result.get("person_id"),
        )

    # Both modules captured answer_command by value in earlier hotfixes.
    conversation.answer_command = live_answer
    v452.answer_command = live_answer

    # Help the command Whisper model keep the intended wording verbatim.
    try:
        from . import assistant_command_stt_patch as command_stt

        example = " Oi, Tonho! Avise que eu estou na porta."
        if example.strip() not in command_stt.COMMAND_PROMPT:
            command_stt.COMMAND_PROMPT += example
    except Exception:
        pass

    # Spatial alerts remain owners of geometry/cooldown. We only observe a
    # successful trigger and optionally enqueue the bell afterwards.
    from .spatial_alerts import SpatialAlertManager

    original_spatial_trigger = SpatialAlertManager._trigger

    def trigger_with_doorbell(
        self: Any,
        rule: dict[str, Any],
        track: Any,
        camera_id: int,
        camera_name: str,
        foot: Any,
        trigger_kind: str,
    ) -> None:
        original_spatial_trigger(self, rule, track, camera_id, camera_name, foot, trigger_kind)
        try:
            rule_id = int(rule["id"])
            if not doorbell_manager.spatial_rule_enabled(rule_id):
                return
            event_id = int(track.event_id) if getattr(track, "event_id", None) else None
            doorbell_manager.queue_spatial_ring(rule_id, event_id)
        except Exception as exc:
            # Campainha é acessória: jamais interrompe tracker/cerca/push espacial.
            self.error = f"Campainha espacial: {exc}"

    SpatialAlertManager._trigger = trigger_with_doorbell
    tools._poi_doorbell_patch_installed = True

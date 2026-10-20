from __future__ import annotations

from typing import Any

from . import body_identity as bi
from . import false_positive_memory as memory


def install() -> None:
    cls = bi.BodyIdentityManager
    if getattr(cls, "_poi_persistent_false_positive_memory", False):
        return

    original_negative_gallery = cls._negative_gallery
    original_record_false_positive = cls.record_false_positive
    original_undo_false_positive = cls.undo_false_positive

    def negative_gallery(self: Any, camera_id: int) -> list[dict[str, Any]]:
        # Keep legacy reviewed negatives for backward compatibility, then append
        # bounded persistent prototypes that survive Timeline retention.
        legacy = original_negative_gallery(self, camera_id)
        try:
            persistent = memory.negative_gallery(int(camera_id))
        except Exception as exc:
            self.error = f"Memória de falso positivo: {exc}"
            persistent = []
        return [*legacy, *persistent]

    def record_false_positive(self: Any, event_id: int) -> None:
        # Preserve the proven legacy write path first. The persistent layer is
        # additive and failure-isolated so manual review can never break ReID.
        original_record_false_positive(self, event_id)
        try:
            memory.learn_event(int(event_id), propagate=True, body_manager=self)
        except Exception as exc:
            self.error = f"Memória persistente de falso positivo: {exc}"

    def undo_false_positive(self: Any, event_id: int) -> None:
        original_undo_false_positive(self, event_id)
        try:
            memory.forget_event(int(event_id))
        except Exception as exc:
            self.error = f"Desaprendizado de falso positivo: {exc}"

    cls._negative_gallery = negative_gallery
    cls.record_false_positive = record_false_positive
    cls.undo_false_positive = undo_false_positive
    cls._poi_persistent_false_positive_memory = True

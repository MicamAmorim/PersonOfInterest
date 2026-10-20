from __future__ import annotations

from typing import Any

from . import body_identity as bi
from . import false_positive_memory as memory
from .db import connection


def _expand_persistent_support(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose bounded manual support to the proven hard-negative ranker.

    rank_hard_negative already requires repeated evidence for the normal reject
    path. A persistent prototype represents several reviewed negatives, so up to
    three virtual copies are supplied according to support_count. This does not
    change any Body ReID positive threshold or scoring rule.
    """
    if not items:
        return []
    prototype_ids = [int(item["prototype_id"]) for item in items if item.get("prototype_id")]
    support: dict[int, int] = {}
    if prototype_ids:
        marks = ",".join("?" for _ in prototype_ids)
        with connection() as conn:
            rows = conn.execute(
                f"SELECT id, support_count FROM false_positive_prototypes WHERE id IN ({marks})",
                prototype_ids,
            ).fetchall()
        support = {int(row["id"]): max(1, int(row["support_count"] or 1)) for row in rows}

    output: list[dict[str, Any]] = []
    for item in items:
        prototype_id = int(item.get("prototype_id") or 0)
        copies = min(3, support.get(prototype_id, 1))
        output.extend(dict(item) for _ in range(copies))
    return output


def install() -> None:
    cls = bi.BodyIdentityManager
    if getattr(cls, "_poi_persistent_false_positive_memory", False):
        return

    original_negative_gallery = cls._negative_gallery
    original_record_false_positive = cls.record_false_positive
    original_undo_false_positive = cls.undo_false_positive

    def negative_gallery(self: Any, camera_id: int) -> list[dict[str, Any]]:
        # Legacy entries remain a migration fallback for historical installations.
        # New reviewed negatives are distilled into bounded persistent prototypes.
        legacy = original_negative_gallery(self, camera_id)
        try:
            persistent = _expand_persistent_support(memory.negative_gallery(int(camera_id)))
        except Exception as exc:
            self.error = f"Memória de falso positivo: {exc}"
            persistent = []
        return [*legacy, *persistent]

    def record_false_positive(self: Any, event_id: int) -> None:
        # Preserve the proven legacy write path first so review is never lost if
        # prototype creation fails. Once persistent learning succeeds, the legacy
        # body_negative_samples row is redundant and is removed, bounding growth.
        original_record_false_positive(self, event_id)
        try:
            result = memory.learn_event(int(event_id), propagate=True, body_manager=self)
            if result.get("learned"):
                with connection() as conn:
                    conn.execute("DELETE FROM body_negative_samples WHERE event_id = ?", (int(event_id),))
                    conn.commit()
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

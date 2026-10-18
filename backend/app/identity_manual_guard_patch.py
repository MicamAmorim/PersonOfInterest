from __future__ import annotations

from typing import Any

from .db import connection, utc_now


def _manual_body_reference(event_id: int) -> tuple[int, str] | None:
    """Return the authoritative manually-confirmed person for an event, if any."""
    with connection() as conn:
        row = conn.execute(
            """SELECT person_id, source
            FROM body_samples
            WHERE event_id = ? AND verified = 1 AND person_id IS NOT NULL
              AND source LIKE 'manual_verified%'
            LIMIT 1""",
            (event_id,),
        ).fetchone()
    if row is None:
        return None
    return int(row["person_id"]), str(row["source"] or "manual_verified")


def _repair_manual_events() -> int:
    """Restore manual event labels that an old face-reindex pass erased.

    Older reindex logic marked every event without a face sample as `pending`.
    The face worker then changed a body-only manually labelled event to `no_face`
    and cleared person_id. The verified body sample still retained the manual
    person label, so it is a reliable source for repairing those events.
    """
    with connection() as conn:
        tables = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if not {"events", "body_samples"}.issubset(tables):
            return 0

        rows = conn.execute(
            """SELECT e.id, bs.person_id
            FROM events e
            JOIN body_samples bs ON bs.event_id = e.id
            WHERE e.person_id IS NULL
              AND COALESCE(e.identity_state, '') <> 'false_positive'
              AND bs.verified = 1
              AND bs.person_id IS NOT NULL
              AND bs.source LIKE 'manual_verified%'"""
        ).fetchall()
        if not rows:
            return 0

        for row in rows:
            conn.execute(
                """UPDATE events
                SET person_id = ?, probable_person_id = NULL, body_confidence = NULL,
                    body_identity_source = NULL, unknown_cluster_id = NULL,
                    identity_state = 'known', identity_confidence = 1.0
                WHERE id = ? AND COALESCE(identity_state, '') <> 'false_positive'""",
                (int(row["person_id"]), int(row["id"])),
            )
        conn.commit()
        return len(rows)


def install() -> None:
    from . import identity as fi

    cls = fi.IdentityManager
    if getattr(cls, "_poi_manual_identity_guard_patch", False):
        return

    original_start = cls.start
    original_set_event_state = cls._set_event_state

    def guarded_start(self: Any) -> None:
        # main.lifespan calls init_db() before manager.start(), so the schema is
        # available here. Repairing historical manual labels before Tonho starts
        # also guarantees that old events are not replayed as fresh greetings.
        try:
            repaired = _repair_manual_events()
            self._manual_identity_repairs = repaired
        except Exception as exc:
            self._manual_identity_repair_error = str(exc)
        original_start(self)

    def guarded_set_event_state(
        self: Any,
        event_id: int,
        state: str,
        person_id: int | None,
        cluster_id: int | None,
        confidence: float | None,
    ) -> None:
        # A face search that fails must never erase an explicit human label.
        if person_id is None and state in {"no_face", "missing_snapshot"}:
            manual = _manual_body_reference(int(event_id))
            if manual is not None:
                manual_person_id, _ = manual
                with connection() as conn:
                    conn.execute(
                        """UPDATE events
                        SET person_id = ?, probable_person_id = NULL, body_confidence = NULL,
                            body_identity_source = NULL, unknown_cluster_id = NULL,
                            identity_state = 'known', identity_confidence = 1.0
                        WHERE id = ?""",
                        (manual_person_id, int(event_id)),
                    )
                    conn.commit()
                return
        original_set_event_state(self, event_id, state, person_id, cluster_id, confidence)

    def safe_reindex(self: Any, *, include_no_face: bool = False) -> dict[str, int]:
        """Reindex face evidence without touching authoritative manual labels."""
        with connection() as conn:
            manual_guard = """
                NOT EXISTS (
                    SELECT 1 FROM body_samples bs
                    WHERE bs.event_id = e.id
                      AND bs.verified = 1
                      AND bs.person_id IS NOT NULL
                      AND bs.source LIKE 'manual_verified%'
                )
            """
            if include_no_face:
                event_rows = conn.execute(
                    f"""SELECT e.id FROM events e
                    WHERE e.snapshot_path IS NOT NULL
                      AND COALESCE(e.identity_state, '') <> 'false_positive'
                      AND {manual_guard}"""
                ).fetchall()
            else:
                event_rows = conn.execute(
                    f"""SELECT e.id FROM events e
                    LEFT JOIN face_samples fs ON fs.event_id = e.id
                    WHERE e.snapshot_path IS NOT NULL
                      AND fs.id IS NULL
                      AND COALESCE(e.identity_state, '') <> 'false_positive'
                      AND {manual_guard}"""
                ).fetchall()

            ids = [int(row["id"]) for row in event_rows]
            if ids:
                marks = ",".join("?" for _ in ids)
                conn.execute(f"UPDATE events SET identity_state = 'pending' WHERE id IN ({marks})", ids)
                if include_no_face:
                    conn.execute(f"DELETE FROM face_samples WHERE event_id IN ({marks})", ids)
            conn.commit()
        return {"queued": len(ids)}

    cls.start = guarded_start
    cls._set_event_state = guarded_set_event_state
    cls.reindex = safe_reindex
    cls._poi_manual_identity_guard_patch = True

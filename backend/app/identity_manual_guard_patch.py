from __future__ import annotations

from typing import Any

from .db import connection


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
    """Restore event truth from persistent human-labelled body references.

    Older face-reindex passes could downgrade a body-only manual label to
    ``no_face`` and clear ``events.person_id``. The body sample still preserves
    the human label (verified=1 + manual_verified*), so that row is the durable
    source used here to heal the event.
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
            WHERE bs.verified = 1
              AND bs.person_id IS NOT NULL
              AND bs.source LIKE 'manual_verified%'
              AND COALESCE(e.identity_state, '') <> 'false_positive'
              AND (
                    e.person_id IS NULL
                 OR e.person_id <> bs.person_id
                 OR COALESCE(e.identity_state, '') <> 'known'
                 OR COALESCE(e.identity_confidence, 0) < 1.0
              )"""
        ).fetchall()
        for row in rows:
            conn.execute(
                """UPDATE events
                SET person_id = ?, probable_person_id = NULL, body_confidence = NULL,
                    body_identity_source = NULL, unknown_cluster_id = NULL,
                    identity_state = 'known', identity_confidence = 1.0
                WHERE id = ? AND COALESCE(identity_state, '') <> 'false_positive'""",
                (int(row["person_id"]), int(row["id"])),
            )
        if rows:
            conn.commit()
        return len(rows)


def _repair_reviewed_false_positives() -> int:
    """Restore manual false-positive state if a stale reindex cleared it.

    ``body_negative_samples`` is durable evidence of an explicit reviewed false
    positive. Undoing a false positive deletes that negative row, so any row that
    still exists here is authoritative even if a stale reindex also changed the
    companion body_samples source.
    """
    with connection() as conn:
        tables = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if not {"events", "body_negative_samples"}.issubset(tables):
            return 0
        rows = conn.execute(
            """SELECT e.id
            FROM events e
            JOIN body_negative_samples bn ON bn.event_id = e.id
            WHERE COALESCE(e.identity_state, '') <> 'false_positive'"""
        ).fetchall()
        for row in rows:
            conn.execute(
                """UPDATE events
                SET person_id = NULL, probable_person_id = NULL, body_confidence = NULL,
                    body_identity_source = NULL, unknown_cluster_id = NULL,
                    identity_state = 'false_positive', identity_confidence = NULL
                WHERE id = ?""",
                (int(row["id"]),),
            )
            conn.execute(
                """UPDATE body_samples
                SET person_id = NULL, verified = 0, source = 'false_positive'
                WHERE event_id = ?""",
                (int(row["id"]),),
            )
        if rows:
            conn.commit()
        return len(rows)


def _repair_authoritative_state() -> tuple[int, int]:
    return _repair_manual_events(), _repair_reviewed_false_positives()


def install() -> None:
    from . import body_identity as bi
    from . import identity as fi

    identity_cls = fi.IdentityManager
    body_cls = bi.BodyIdentityManager
    if getattr(identity_cls, "_poi_manual_identity_guard_patch_v2", False):
        return

    original_identity_start = identity_cls.start
    original_set_event_state = identity_cls._set_event_state
    original_body_sync = body_cls._sync_verified_labels

    def guarded_start(self: Any) -> None:
        # main.lifespan calls init_db() before manager.start(). Repair before
        # worker threads and before Tonho can evaluate old events.
        try:
            manual, negatives = _repair_authoritative_state()
            self._manual_identity_repairs = manual
            self._reviewed_negative_repairs = negatives
        except Exception as exc:
            self._manual_identity_repair_error = str(exc)
        original_identity_start(self)

    def guarded_set_event_state(
        self: Any,
        event_id: int,
        state: str,
        person_id: int | None,
        cluster_id: int | None,
        confidence: float | None,
    ) -> None:
        # A face search failure can never erase an explicit human identity.
        if person_id is None and state in {"no_face", "missing_snapshot", "pending"}:
            manual = _manual_body_reference(int(event_id))
            if manual is not None:
                manual_person_id, _ = manual
                with connection() as conn:
                    conn.execute(
                        """UPDATE events
                        SET person_id = ?, probable_person_id = NULL, body_confidence = NULL,
                            body_identity_source = NULL, unknown_cluster_id = NULL,
                            identity_state = 'known', identity_confidence = 1.0
                        WHERE id = ? AND COALESCE(identity_state, '') <> 'false_positive'""",
                        (manual_person_id, int(event_id)),
                    )
                    conn.commit()
                return
        original_set_event_state(self, event_id, state, person_id, cluster_id, confidence)

    def safe_reindex(self: Any, *, include_no_face: bool = False) -> dict[str, int]:
        """Reindex face evidence without touching authoritative human review."""
        with connection() as conn:
            authority_guard = """
                NOT EXISTS (
                    SELECT 1 FROM body_samples bs
                    WHERE bs.event_id = e.id
                      AND (
                            (bs.verified = 1 AND bs.person_id IS NOT NULL AND bs.source LIKE 'manual_verified%')
                         OR bs.source = 'false_positive'
                      )
                )
                AND NOT EXISTS (
                    SELECT 1 FROM body_negative_samples bn WHERE bn.event_id = e.id
                )
            """
            if include_no_face:
                event_rows = conn.execute(
                    f"""SELECT e.id FROM events e
                    WHERE e.snapshot_path IS NOT NULL
                      AND COALESCE(e.identity_state, '') <> 'false_positive'
                      AND {authority_guard}"""
                ).fetchall()
            else:
                event_rows = conn.execute(
                    f"""SELECT e.id FROM events e
                    LEFT JOIN face_samples fs ON fs.event_id = e.id
                    WHERE e.snapshot_path IS NOT NULL
                      AND fs.id IS NULL
                      AND COALESCE(e.identity_state, '') <> 'false_positive'
                      AND {authority_guard}"""
                ).fetchall()

            ids = [int(row["id"]) for row in event_rows]
            if ids:
                marks = ",".join("?" for _ in ids)
                conn.execute(f"UPDATE events SET identity_state = 'pending' WHERE id IN ({marks})", ids)
                if include_no_face:
                    conn.execute(f"DELETE FROM face_samples WHERE event_id IN ({marks})", ids)
            conn.commit()
        # Heal any stale authoritative rows left by older versions before return.
        manual, negatives = _repair_authoritative_state()
        return {"queued": len(ids), "manual_repaired": manual, "false_positive_repaired": negatives}

    def guarded_body_sync(self: Any) -> None:
        # Continuous integrity check: even if another legacy path writes stale
        # event state, the body worker heals authoritative human review on its
        # next normal synchronization cycle.
        try:
            _repair_authoritative_state()
        except Exception:
            pass
        original_body_sync(self)

    identity_cls.start = guarded_start
    identity_cls._set_event_state = guarded_set_event_state
    identity_cls.reindex = safe_reindex
    body_cls._sync_verified_labels = guarded_body_sync
    identity_cls._poi_manual_identity_guard_patch_v2 = True

from __future__ import annotations

from typing import Any

from . import body_identity as bi


def install() -> None:
    """Bound historical ReID/backfill work without changing identity semantics.

    Older reviews may predate working OSNet embeddings or may reference missing
    snapshots. Likewise, a malformed historical body crop must not remain at the
    head of the body-ReID queue forever. Record one-time outcomes so newer events
    continue to be processed.
    """
    cls = bi.BodyIdentityManager
    if getattr(cls, "_poi_negative_backfill_guard", False):
        return

    original_schema = cls._ensure_aux_schema

    def ensure_aux_schema(self: Any) -> None:
        original_schema(self)
        with bi.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS body_negative_backfill_state (
                    event_id INTEGER PRIMARY KEY,
                    outcome TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_body_negative_backfill_outcome
                    ON body_negative_backfill_state(outcome, updated_at DESC);

                CREATE TABLE IF NOT EXISTS body_index_state (
                    event_id INTEGER PRIMARY KEY,
                    outcome TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_body_index_outcome
                    ON body_index_state(outcome, updated_at DESC);
                """
            )
            conn.commit()

    def process_pending_once(self: Any, limit: int = 6) -> int:
        self._ensure_aux_schema()
        with bi.connection() as conn:
            rows = conn.execute(
                """SELECT e.* FROM events e
                LEFT JOIN body_samples bs ON bs.event_id = e.id
                LEFT JOIN body_index_state bis ON bis.event_id = e.id
                WHERE bs.id IS NULL AND bis.event_id IS NULL
                  AND e.snapshot_path IS NOT NULL
                  AND COALESCE(e.identity_state, '') <> 'false_positive'
                ORDER BY e.created_at ASC LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()

        touched = 0
        for row in rows:
            if self.stop_event.is_set():
                break
            event = dict(row)
            # Crop/path/bbox failures are event-specific and should be skipped
            # permanently. Model/runtime errors still propagate to _run so the
            # manager can report a real engine failure rather than hiding it.
            embedded = self._event_embedding(event)
            if embedded is None:
                with bi.connection() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO body_index_state(event_id, outcome, updated_at)
                        VALUES (?, 'unavailable', ?)""",
                        (int(event["id"]), bi.utc_now()),
                    )
                    conn.commit()
                touched += 1
                continue

            embedding, quality = embedded
            self._persist_body_sample(event, embedding, quality)
            with bi.connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO body_index_state(event_id, outcome, updated_at)
                    VALUES (?, 'indexed', ?)""",
                    (int(event["id"]), bi.utc_now()),
                )
                conn.commit()
            touched += 1
        return touched

    def backfill_hard_negatives(self: Any, limit: int = 4) -> int:
        self._ensure_aux_schema()
        with bi.connection() as conn:
            rows = conn.execute(
                """SELECT e.id FROM events e
                LEFT JOIN body_negative_samples bn ON bn.event_id = e.id
                LEFT JOIN body_negative_backfill_state bs ON bs.event_id = e.id
                WHERE e.identity_state = 'false_positive'
                  AND e.snapshot_path IS NOT NULL
                  AND bn.id IS NULL
                  AND bs.event_id IS NULL
                  AND COALESCE(e.body_identity_source, '') <> 'hard_negative_auto'
                ORDER BY e.created_at DESC LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()

        attempted = 0
        for row in rows:
            if self.stop_event.is_set():
                break
            event_id = int(row["id"])
            self.record_false_positive(event_id)
            with bi.connection() as conn:
                indexed = conn.execute(
                    "SELECT 1 FROM body_negative_samples WHERE event_id = ?",
                    (event_id,),
                ).fetchone() is not None
                conn.execute(
                    """INSERT OR REPLACE INTO body_negative_backfill_state(event_id, outcome, updated_at)
                    VALUES (?, ?, ?)""",
                    (event_id, "indexed" if indexed else "unavailable", bi.utc_now()),
                )
                conn.commit()
            attempted += 1
        return attempted

    cls._ensure_aux_schema = ensure_aux_schema
    cls.process_pending_once = process_pending_once
    cls._backfill_hard_negatives = backfill_hard_negatives
    cls._poi_negative_backfill_guard = True

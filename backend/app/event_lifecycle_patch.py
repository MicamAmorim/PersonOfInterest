from __future__ import annotations

from typing import Any

from . import alerts
from . import body_identity as bi
from .db import connection, utc_now
from .tracking_v5_patch import ensure_schema


def _body_process_pending(self: Any, limit: int = 6) -> int:
    """Do not let legacy single-frame Body ReID race a collecting track."""
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT e.* FROM events e
            LEFT JOIN body_samples bs ON bs.event_id = e.id
            WHERE bs.id IS NULL AND e.snapshot_path IS NOT NULL
              AND COALESCE(e.identity_state, '') NOT IN ('false_positive', 'collecting')
            ORDER BY e.created_at ASC LIMIT ?""",
            (max(1, int(limit)),),
        ).fetchall()
    processed = 0
    for row in rows:
        if self.stop_event.is_set():
            break
        event = dict(row)
        embedded = self._event_embedding(event)
        if embedded is None:
            continue
        embedding, quality = embedded
        self._persist_body_sample(event, embedding, quality)
        processed += 1
    return processed


def _body_refresh_probables(self: Any, limit: int = 100) -> None:
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT e.id, bs.embedding, bs.quality
            FROM events e JOIN body_samples bs ON bs.event_id = e.id
            WHERE e.person_id IS NULL
              AND COALESCE(e.identity_state, '') NOT IN ('false_positive', 'collecting')
            ORDER BY e.created_at DESC LIMIT ?""",
            (max(1, int(limit)),),
        ).fetchall()
    for row in rows:
        embedding = bi._blob_to_vector(row["embedding"])
        if embedding is None:
            continue
        quality = float(row["quality"] or 0.0)
        if self._check_hard_negative(int(row["id"]), embedding, quality):
            continue
        self._score_event(int(row["id"]), embedding=embedding, quality=quality)


def _install_hard_negative_gate() -> None:
    cls = bi.BodyIdentityManager
    if getattr(cls, "_poi_v5_hard_negative_gate", False):
        return
    original = cls._check_hard_negative

    def check(self: Any, event_id: int, embedding: Any, quality: float) -> bool:
        ensure_schema()
        with connection() as conn:
            row = conn.execute(
                """SELECT e.identity_state, e.has_face, e.track_status,
                    COALESCE(bs.temporal_support, 1) temporal_support
                FROM events e LEFT JOIN body_samples bs ON bs.event_id = e.id
                WHERE e.id = ?""",
                (event_id,),
            ).fetchone()
        if row is None:
            return False
        if str(row["identity_state"] or "") in {"collecting", "pending", "false_positive"}:
            return False
        # A detected face is strong evidence that this is a real person even if
        # facial identity is still unknown. Body hard-negatives must not erase it.
        if bool(row["has_face"]):
            return False
        # Repeated body observations are required before an object can be learned
        # as a false-positive. One accidental crop can never auto-reject a track.
        if int(row["temporal_support"] or 1) < 3:
            return False
        return original(self, event_id, embedding, quality)

    cls._check_hard_negative = check
    cls._poi_v5_hard_negative_gate = True


def _alert_evaluate_new_events(self: Any) -> int:
    """Known identity can alert promptly; unknown identity waits for track end."""
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT e.*, c.name camera_name, c.location camera_location, p.name person_name
            FROM events e
            JOIN cameras c ON c.id = e.camera_id
            LEFT JOIN persons p ON p.id = e.person_id
            LEFT JOIN alert_event_state aes ON aes.event_id = e.id
            WHERE aes.event_id IS NULL AND e.created_at >= ?
              AND COALESCE(e.identity_state, 'pending') NOT IN ('pending', 'collecting')
              AND (
                    e.person_id IS NOT NULL
                    OR COALESCE(e.track_status, 'ended') = 'ended'
                    OR e.identity_state = 'false_positive'
                  )
            ORDER BY e.created_at ASC LIMIT 30""",
            (self.started_at,),
        ).fetchall()
    processed = 0
    for row in rows:
        event = dict(row)
        self._evaluate_event(event)
        with connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO alert_event_state(event_id, evaluated_at) VALUES (?, ?)",
                (event["id"], utc_now()),
            )
            conn.commit()
        processed += 1
    return processed


def install() -> None:
    body_cls = bi.BodyIdentityManager
    body_cls.process_pending_once = _body_process_pending
    body_cls._refresh_probables = _body_refresh_probables
    _install_hard_negative_gate()

    alert_cls = alerts.AlertManager
    if not getattr(alert_cls, "_poi_v5_event_lifecycle", False):
        alert_cls.evaluate_new_events = _alert_evaluate_new_events
        alert_cls._poi_v5_event_lifecycle = True

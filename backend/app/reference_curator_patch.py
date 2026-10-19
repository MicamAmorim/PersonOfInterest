from __future__ import annotations

from typing import Any

from . import body_identity as bi
from . import db
from . import identity as fi
from . import tracking_v5_patch as tracking
from .db import connection


_SCHEMA_READY = False


def _columns(conn: Any, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn: Any, table: str, name: str, ddl: str) -> None:
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def ensure_curator_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    tracking.ensure_schema()
    with connection() as conn:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "face_samples" not in tables or "body_samples" not in tables:
            return
        _ensure_column(conn, "face_samples", "active", "active INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "face_samples", "user_disabled", "user_disabled INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "body_samples", "user_disabled", "user_disabled INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE face_samples SET active = 1 WHERE active IS NULL")
        conn.execute("UPDATE face_samples SET user_disabled = 0 WHERE user_disabled IS NULL")
        conn.execute("UPDATE body_samples SET user_disabled = 0 WHERE user_disabled IS NULL")
        conn.commit()
    _SCHEMA_READY = True


def _face_match_curated(self: Any, embedding: Any) -> tuple[int | None, float | None]:
    ensure_curator_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT person_id, embedding FROM face_samples
            WHERE person_id IS NOT NULL AND active = 1 AND user_disabled = 0
            UNION ALL
            SELECT person_id, embedding FROM person_face_anchors
            WHERE active = 1"""
        ).fetchall()
    best_person: int | None = None
    best_score = -1.0
    for row in rows:
        candidate = fi._blob_to_vector(row["embedding"])
        if candidate is None:
            continue
        score = fi._cosine(embedding, candidate)
        if score > best_score:
            best_score = score
            best_person = int(row["person_id"])
    if best_person is not None and best_score >= fi.IDENTITY_KNOWN_THRESHOLD:
        return best_person, best_score
    return None, None


def _trusted_gallery_curated(self: Any) -> list[dict[str, Any]]:
    ensure_curator_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT person_id, embedding, quality, source FROM body_samples
            WHERE verified = 1 AND person_id IS NOT NULL
              AND active = 1 AND user_disabled = 0 AND trusted = 1
              AND source NOT IN ('false_positive', 'auto_false_positive') AND quality >= 0.38
            UNION ALL
            SELECT person_id, embedding, quality, source FROM person_body_anchors
            WHERE active = 1 AND quality >= 0.38"""
        ).fetchall()
    return [dict(row) for row in rows]


def _install_face_persistence_guard() -> None:
    cls = fi.IdentityManager
    if getattr(cls, "_poi_reference_curator_face_persist", False):
        return
    original = cls._persist_sample

    def persist(self: Any, event: dict[str, Any], embedding: Any, crop_relative: str | None, quality: float, **kwargs: Any) -> None:
        ensure_curator_schema()
        event_id = int(event["id"])
        with connection() as conn:
            previous = conn.execute(
                "SELECT active, user_disabled FROM face_samples WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        original(self, event, embedding, crop_relative, quality, **kwargs)
        if previous is not None and bool(previous["user_disabled"]):
            with connection() as conn:
                conn.execute(
                    "UPDATE face_samples SET active = 0, user_disabled = 1 WHERE event_id = ?",
                    (event_id,),
                )
                conn.commit()

    cls._persist_sample = persist
    cls._poi_reference_curator_face_persist = True


def _install_body_sync_guard() -> None:
    cls = bi.BodyIdentityManager
    if getattr(cls, "_poi_reference_curator_body_sync", False):
        return
    original = cls._sync_verified_labels

    def sync(self: Any) -> None:
        ensure_curator_schema()
        with connection() as conn:
            disabled_ids = [
                int(row["id"]) for row in conn.execute(
                    "SELECT id FROM body_samples WHERE user_disabled = 1"
                ).fetchall()
            ]
        original(self)
        if disabled_ids:
            marks = ",".join("?" for _ in disabled_ids)
            with connection() as conn:
                conn.execute(
                    f"UPDATE body_samples SET active = 0, user_disabled = 1 WHERE id IN ({marks})",
                    disabled_ids,
                )
                conn.commit()

    cls._sync_verified_labels = sync
    cls._poi_reference_curator_body_sync = True


def _install_body_promotion_guard() -> None:
    if getattr(tracking, "_poi_reference_curator_promotion", False):
        return
    original = tracking._promote_face_linked_body

    def promote(track: Any, aggregate: Any) -> None:
        ensure_curator_schema()
        if getattr(track, "event_id", None) is not None:
            with connection() as conn:
                row = conn.execute(
                    "SELECT user_disabled FROM body_samples WHERE event_id = ?",
                    (int(track.event_id),),
                ).fetchone()
            if row is not None and bool(row["user_disabled"]):
                return
        original(track, aggregate)

    tracking._promote_face_linked_body = promote
    tracking._poi_reference_curator_promotion = True


def _install_manual_reactivation() -> None:
    body_cls = bi.BodyIdentityManager
    if not getattr(body_cls, "_poi_reference_curator_confirm", False):
        original_confirm = body_cls.confirm_event_identity

        def confirm(self: Any, event_id: int, person_id: int) -> None:
            original_confirm(self, event_id, person_id)
            ensure_curator_schema()
            with connection() as conn:
                conn.execute(
                    """UPDATE body_samples SET active = 1, user_disabled = 0
                    WHERE event_id = ? AND person_id = ?""",
                    (event_id, person_id),
                )
                conn.commit()

        body_cls.confirm_event_identity = confirm
        body_cls._poi_reference_curator_confirm = True

    identity_cls = fi.IdentityManager
    if not getattr(identity_cls, "_poi_reference_curator_assign", False):
        original_assign_event = identity_cls.assign_event
        original_assign_cluster = identity_cls.assign_cluster

        def assign_event(self: Any, event_id: int, *, person_id: int | None = None, name: str | None = None) -> dict[str, Any]:
            result = original_assign_event(self, event_id, person_id=person_id, name=name)
            ensure_curator_schema()
            resolved = int(result["person_id"])
            with connection() as conn:
                conn.execute(
                    """UPDATE face_samples SET active = 1, user_disabled = 0
                    WHERE event_id = ? AND person_id = ?""",
                    (event_id, resolved),
                )
                conn.commit()
            return result

        def assign_cluster(self: Any, cluster_id: int, *, person_id: int | None = None, name: str | None = None) -> dict[str, Any]:
            result = original_assign_cluster(self, cluster_id, person_id=person_id, name=name)
            ensure_curator_schema()
            resolved = int(result["person_id"])
            with connection() as conn:
                conn.execute(
                    """UPDATE face_samples SET active = 1, user_disabled = 0
                    WHERE person_id = ? AND cluster_id IS NULL""",
                    (resolved,),
                )
                conn.commit()
            return result

        identity_cls.assign_event = assign_event
        identity_cls.assign_cluster = assign_cluster
        identity_cls._poi_reference_curator_assign = True


def install() -> None:
    if getattr(fi, "_poi_reference_curator_installed", False):
        return

    original_init_db = db.init_db

    def init_db_curator() -> None:
        global _SCHEMA_READY
        original_init_db()
        _SCHEMA_READY = False
        ensure_curator_schema()

    db.init_db = init_db_curator

    fi.IdentityManager._match_known = _face_match_curated
    bi.BodyIdentityManager._gallery = _trusted_gallery_curated
    _install_face_persistence_guard()
    _install_body_sync_guard()
    _install_body_promotion_guard()
    _install_manual_reactivation()

    from .api_v34 import router as base_router
    from .reference_curator_api import router as curator_router
    if not getattr(base_router, "_poi_reference_curator_router", False):
        base_router.include_router(curator_router)
        base_router._poi_reference_curator_router = True

    fi._poi_reference_curator_installed = True

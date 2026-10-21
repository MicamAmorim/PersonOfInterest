from __future__ import annotations

from typing import Any

from . import identity as fi
from .db import connection, utc_now
from .tracking_v5_patch import ensure_schema


def _manual_person(event_id: int) -> int | None:
    """Return the human-authoritative identity for an event, if one exists."""
    ensure_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT person_id, identity_origin, identity_state
            FROM events WHERE id = ?""",
            (int(event_id),),
        ).fetchone()
    if row is None:
        return None
    if str(row["identity_state"] or "") == "false_positive":
        return None
    if str(row["identity_origin"] or "") != "manual" or row["person_id"] is None:
        return None
    return int(row["person_id"])


def _repair_cluster(cluster_id: int | None) -> None:
    """Rebuild a face cluster if a late worker had already scored a manual event into it."""
    if cluster_id is None:
        return
    with connection() as conn:
        rows = conn.execute(
            """SELECT fs.embedding, fs.crop_path, fs.quality, e.created_at
            FROM face_samples fs
            JOIN events e ON e.id = fs.event_id
            WHERE fs.cluster_id = ?
            ORDER BY e.created_at ASC""",
            (int(cluster_id),),
        ).fetchall()
        if not rows:
            conn.execute("DELETE FROM unknown_clusters WHERE id = ?", (int(cluster_id),))
            conn.commit()
            return

        vectors = [fi._blob_to_vector(row["embedding"]) for row in rows]
        vectors = [vector for vector in vectors if vector is not None]
        if not vectors:
            conn.execute("DELETE FROM unknown_clusters WHERE id = ?", (int(cluster_id),))
            conn.commit()
            return

        centroid = fi._normalize(sum(vectors) / max(1, len(vectors)))
        best = max(rows, key=lambda row: float(row["quality"] or 0.0))
        conn.execute(
            """UPDATE unknown_clusters
            SET centroid = ?, sample_count = ?, representative_crop_path = ?,
                representative_quality = ?, first_seen = ?, last_seen = ?, updated_at = ?
            WHERE id = ?""",
            (
                fi._vector_to_blob(centroid), len(rows), best["crop_path"],
                float(best["quality"] or 0.0), str(rows[0]["created_at"]),
                str(rows[-1]["created_at"]), utc_now(), int(cluster_id),
            ),
        )
        conn.commit()


def install() -> None:
    """Make manual Timeline review win over an in-flight automatic face result.

    IdentityManager.process_pending_once() reads a batch before doing expensive
    face inference. A user may manually classify one of those events while the
    worker is still processing its old in-memory row. Without this final-write
    guard, _persist_sample() can commit after the user's click and replace the
    manually chosen person with an automatic/unknown result. The UI then looks
    correct until the next reload.

    Human review is authoritative for that event. We still keep the freshly
    computed face embedding, but attach it to the manually selected person and
    never let the late worker change the event back to automatic identity.
    """
    cls = fi.IdentityManager
    if getattr(cls, "_poi_manual_persistence_guard", False):
        return

    original_persist = cls._persist_sample

    def persist_manual_safe(
        self: Any,
        event: dict[str, Any],
        embedding: Any,
        crop_relative: str | None,
        quality: float,
        **kwargs: Any,
    ) -> None:
        event_id = int(event["id"])
        manual_person_id = _manual_person(event_id)
        proposed_cluster = kwargs.get("cluster_id")

        if manual_person_id is None:
            original_persist(self, event, embedding, crop_relative, quality, **kwargs)
            return

        safe_kwargs = dict(kwargs)
        safe_kwargs.update({
            "person_id": manual_person_id,
            "cluster_id": None,
            "identity_state": "known",
            "identity_confidence": 1.0,
        })
        original_persist(self, event, embedding, crop_relative, quality, **safe_kwargs)

        # Reassert all manual provenance fields in the same final-write path.
        # This also protects against older wrappers that only preserve
        # identity_origin while allowing person_id/state to be rewritten.
        with connection() as conn:
            conn.execute(
                """UPDATE events SET person_id = ?, probable_person_id = NULL,
                    body_confidence = NULL, body_identity_source = NULL,
                    unknown_cluster_id = NULL, identity_state = 'known',
                    identity_confidence = 1.0, identity_origin = 'manual',
                    assistant_eligible = 0
                WHERE id = ? AND COALESCE(identity_state, '') <> 'false_positive'""",
                (manual_person_id, event_id),
            )
            conn.execute(
                "UPDATE face_samples SET person_id = ?, cluster_id = NULL WHERE event_id = ?",
                (manual_person_id, event_id),
            )
            conn.commit()

        # _match_or_create_cluster() may have run just before this guard noticed
        # the manual review. Rebuild that cluster from its real remaining samples
        # so sample_count/centroid do not keep the manually reviewed embedding.
        if proposed_cluster is not None:
            try:
                _repair_cluster(int(proposed_cluster))
            except Exception:
                pass

    cls._persist_sample = persist_manual_safe
    cls._poi_manual_persistence_guard = True

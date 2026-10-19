from __future__ import annotations

from typing import Any

from . import body_identity as bi
from .db import connection, utc_now
from .tracking_v5_patch import (
    V5_BODY_TRUST_MIN_QUALITY,
    V5_BODY_TRUST_MIN_STABILITY,
    V5_BODY_TRUST_MIN_SUPPORT,
    ensure_schema,
)


def _sync_verified_labels_v5(self: Any) -> None:
    """Synchronize event labels without erasing temporal/manual trust provenance."""
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT bs.event_id, bs.person_id sample_person, bs.source, bs.trusted,
                bs.temporal_support, bs.stability, bs.quality,
                e.person_id event_person, e.identity_origin,
                EXISTS(SELECT 1 FROM face_samples fs
                       WHERE fs.event_id = e.id AND fs.person_id = e.person_id) AS face_verified
            FROM body_samples bs JOIN events e ON e.id = bs.event_id
            WHERE COALESCE(e.identity_state, '') <> 'false_positive'"""
        ).fetchall()
        now = utc_now()
        changed = False
        for row in rows:
            event_person = row["event_person"]
            if event_person is None:
                continue
            source = str(row["source"] or "")
            # Existing databases predate identity_origin. Their durable provenance
            # is the body sample source, so keep manual_verified variants trusted.
            manual = str(row["identity_origin"] or "") == "manual" or "manual" in source
            face_verified = bool(row["face_verified"])
            support = int(row["temporal_support"] or 1)
            stability = float(row["stability"] or 0.0)
            quality = float(row["quality"] or 0.0)
            temporal_trusted = (
                face_verified
                and support >= V5_BODY_TRUST_MIN_SUPPORT
                and stability >= V5_BODY_TRUST_MIN_STABILITY
                and quality >= V5_BODY_TRUST_MIN_QUALITY
            )
            if manual:
                desired_source = "face_verified_manual" if face_verified else "manual_verified"
                desired_trusted = 1
            elif temporal_trusted:
                desired_source = "face_verified_trusted"
                desired_trusted = 1
            else:
                desired_source = "face_verified" if face_verified else (source or "unlabeled")
                desired_trusted = 0
            if (
                row["sample_person"] != event_person
                or source != desired_source
                or int(row["trusted"] or 0) != desired_trusted
            ):
                conn.execute(
                    """UPDATE body_samples SET person_id = ?, verified = 1, source = ?, trusted = ?,
                        active = 1, updated_at = ? WHERE event_id = ?""",
                    (event_person, desired_source, desired_trusted, now, row["event_id"]),
                )
                conn.execute("DELETE FROM body_negative_exemptions WHERE event_id = ?", (row["event_id"],))
                conn.execute(
                    "UPDATE events SET probable_person_id = NULL, body_confidence = NULL, body_identity_source = NULL WHERE id = ?",
                    (row["event_id"],),
                )
                changed = True
        if changed:
            conn.commit()


def install() -> None:
    cls = bi.BodyIdentityManager
    if getattr(cls, "_poi_v5_trust_sync", False):
        return
    cls._sync_verified_labels = _sync_verified_labels_v5
    cls._poi_v5_trust_sync = True

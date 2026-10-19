from __future__ import annotations

from typing import Any

from . import identity as fi
from . import identity_manual_guard_patch as guard
from .db import connection
from .tracking_v5_patch import ensure_schema


def _manual_body_reference_v5(event_id: int) -> tuple[int, str] | None:
    ensure_schema()
    with connection() as conn:
        event = conn.execute(
            "SELECT person_id, identity_origin FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if event and event["person_id"] is not None and str(event["identity_origin"] or "") == "manual":
            return int(event["person_id"]), "manual_event"
        row = conn.execute(
            """SELECT person_id, source FROM body_samples
            WHERE event_id = ? AND verified = 1 AND person_id IS NOT NULL
              AND source LIKE '%manual%'
            LIMIT 1""",
            (event_id,),
        ).fetchone()
    if row is None:
        return None
    return int(row["person_id"]), str(row["source"] or "manual_verified")


def _repair_manual_events_v5() -> int:
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT e.id,
                COALESCE(
                    CASE WHEN e.identity_origin = 'manual' THEN e.person_id END,
                    bs.person_id
                ) authoritative_person
            FROM events e
            LEFT JOIN body_samples bs ON bs.event_id = e.id
                AND bs.verified = 1 AND bs.person_id IS NOT NULL AND bs.source LIKE '%manual%'
            WHERE COALESCE(e.identity_state, '') <> 'false_positive'
              AND (
                    (e.identity_origin = 'manual' AND e.person_id IS NOT NULL)
                    OR bs.person_id IS NOT NULL
                  )
            GROUP BY e.id
            HAVING authoritative_person IS NOT NULL
              AND (
                    e.person_id IS NULL
                    OR e.person_id <> authoritative_person
                    OR COALESCE(e.identity_state, '') <> 'known'
                    OR COALESCE(e.identity_confidence, 0) < 1.0
                    OR COALESCE(e.identity_origin, '') <> 'manual'
                    OR COALESCE(e.assistant_eligible, 1) <> 0
                  )"""
        ).fetchall()
        for row in rows:
            conn.execute(
                """UPDATE events SET person_id = ?, probable_person_id = NULL,
                    body_confidence = NULL, body_identity_source = NULL,
                    unknown_cluster_id = NULL, identity_state = 'known',
                    identity_confidence = 1.0, identity_origin = 'manual',
                    assistant_eligible = 0
                WHERE id = ? AND COALESCE(identity_state, '') <> 'false_positive'""",
                (int(row["authoritative_person"]), int(row["id"])),
            )
        if rows:
            conn.commit()
        return len(rows)


def _safe_reindex_v5(self: Any, *, include_no_face: bool = False) -> dict[str, int]:
    ensure_schema()
    with connection() as conn:
        authority_guard = """
            COALESCE(e.identity_origin, '') <> 'manual'
            AND NOT EXISTS (
                SELECT 1 FROM body_samples bs
                WHERE bs.event_id = e.id
                  AND (
                        (bs.verified = 1 AND bs.person_id IS NOT NULL AND bs.source LIKE '%manual%')
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
                WHERE e.snapshot_path IS NOT NULL AND fs.id IS NULL
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
    manual, negatives = guard._repair_authoritative_state()
    return {"queued": len(ids), "manual_repaired": manual, "false_positive_repaired": negatives}


def install() -> None:
    if getattr(fi.IdentityManager, "_poi_v5_manual_integrity", False):
        return
    # The already-installed guard resolves these helpers from module globals at
    # runtime, so replacing them upgrades its behavior without stacking another
    # event-state wrapper.
    guard._manual_body_reference = _manual_body_reference_v5
    guard._repair_manual_events = _repair_manual_events_v5
    fi.IdentityManager.reindex = _safe_reindex_v5
    fi.IdentityManager._poi_v5_manual_integrity = True

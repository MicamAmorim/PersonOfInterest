from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any

from . import body_identity as bi
from . import identity_diagnostics_patch as diagnostics
from .db import connection
from .tracking_v5_patch import ensure_schema


def _csv_text(rows: list[dict[str, Any]], fields: list[str]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field) for field in fields})
    return stream.getvalue()


def install() -> None:
    if getattr(diagnostics, "_poi_v5_diagnostics", False):
        return
    original_build = diagnostics._build_zip

    def build_zip_v5(days: int, max_samples: int, pair_limit: int) -> bytes:
        ensure_schema()
        base = original_build(days, max_samples, pair_limit)
        with connection() as conn:
            body_rows = [dict(row) for row in conn.execute(
                """SELECT id sample_id, event_id, camera_id, person_id, quality, source,
                    verified, trusted, active, temporal_support, track_id, stability,
                    created_at, updated_at
                FROM body_samples WHERE person_id IS NOT NULL
                ORDER BY created_at DESC LIMIT ?""",
                (max(20, min(2000, int(max_samples))),),
            ).fetchall()]
            track_rows = [dict(row) for row in conn.execute(
                """SELECT e.id event_id, e.camera_id, e.track_id, e.person_id,
                    e.probable_person_id, e.identity_state, e.identity_origin,
                    e.track_status, e.observation_count, e.best_frame_quality,
                    e.best_face_quality, e.best_body_quality, e.created_at,
                    e.last_seen_at, e.ended_at
                FROM events e ORDER BY e.created_at DESC LIMIT 5000"""
            ).fetchall()]
            face_anchor_count = int(conn.execute("SELECT COUNT(*) FROM person_face_anchors WHERE active = 1").fetchone()[0])
            body_anchor_count = int(conn.execute("SELECT COUNT(*) FROM person_body_anchors WHERE active = 1").fetchone()[0])
            trusted = int(conn.execute(
                "SELECT COUNT(*) FROM body_samples WHERE verified = 1 AND person_id IS NOT NULL AND active = 1 AND trusted = 1"
            ).fetchone()[0])
            quarantine = int(conn.execute(
                "SELECT COUNT(*) FROM body_samples WHERE verified = 1 AND person_id IS NOT NULL AND active = 1 AND trusted = 0"
            ).fetchone()[0])
            temporal = int(conn.execute(
                "SELECT COUNT(*) FROM body_samples WHERE temporal_support >= 2"
            ).fetchone()[0])

        source = zipfile.ZipFile(io.BytesIO(base), "r")
        manifest = json.loads(source.read("manifest.json").decode("utf-8"))
        manifest["format"] = "PersonOfInterest identity calibration diagnostic v2"
        manifest["v5_persistent_identity"] = {
            "trusted_body_samples": trusted,
            "quarantined_body_samples": quarantine,
            "temporally_aggregated_body_samples": temporal,
            "manual_face_anchors": face_anchor_count,
            "manual_body_anchors": body_anchor_count,
            "body_matcher": "mean(top-3 trusted anchors per person)",
            "single_frame_auto_enrollment": False,
        }
        manifest.setdefault("privacy", {})["v5_raw_track_embeddings_included"] = False

        body_fields = [
            "sample_id", "event_id", "camera_id", "person_id", "quality", "source",
            "verified", "trusted", "active", "temporal_support", "track_id", "stability",
            "created_at", "updated_at",
        ]
        track_fields = [
            "event_id", "camera_id", "track_id", "person_id", "probable_person_id",
            "identity_state", "identity_origin", "track_status", "observation_count",
            "best_frame_quality", "best_face_quality", "best_body_quality",
            "created_at", "last_seen_at", "ended_at",
        ]

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for info in source.infolist():
                if info.filename == "manifest.json":
                    continue
                archive.writestr(info, source.read(info.filename))
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("body_trust_metadata.csv", _csv_text(body_rows, body_fields))
            archive.writestr("track_lifecycle_metadata.csv", _csv_text(track_rows, track_fields))
        source.close()
        return output.getvalue()

    diagnostics._build_zip = build_zip_v5
    diagnostics._poi_v5_diagnostics = True

    cls = bi.BodyIdentityManager
    if not getattr(cls, "_poi_v5_state_counts", False):
        original_state = cls.state

        def state_v5(self: Any) -> dict[str, Any]:
            data = original_state(self)
            try:
                ensure_schema()
                with connection() as conn:
                    data["trusted_samples"] = int(conn.execute(
                        "SELECT COUNT(*) FROM body_samples WHERE verified = 1 AND person_id IS NOT NULL AND active = 1 AND trusted = 1"
                    ).fetchone()[0])
                    data["quarantined_samples"] = int(conn.execute(
                        "SELECT COUNT(*) FROM body_samples WHERE verified = 1 AND person_id IS NOT NULL AND active = 1 AND trusted = 0"
                    ).fetchone()[0])
                    data["temporal_samples"] = int(conn.execute(
                        "SELECT COUNT(*) FROM body_samples WHERE temporal_support >= 2"
                    ).fetchone()[0])
                    data["manual_body_anchors"] = int(conn.execute(
                        "SELECT COUNT(*) FROM person_body_anchors WHERE active = 1"
                    ).fetchone()[0])
            except Exception:
                data.setdefault("trusted_samples", 0)
                data.setdefault("quarantined_samples", 0)
                data.setdefault("temporal_samples", 0)
                data.setdefault("manual_body_anchors", 0)
            return data

        cls.state = state_v5
        cls._poi_v5_state_counts = True

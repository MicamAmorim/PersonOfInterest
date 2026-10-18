from __future__ import annotations

import csv
import io
import json
import random
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any


def _csv_text(rows: list[dict[str, Any]], fields: list[str]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field) for field in fields})
    return stream.getvalue()


def _vector(blob: bytes | memoryview | None) -> Any | None:
    if not blob:
        return None
    try:
        import numpy as np  # type: ignore

        value = np.frombuffer(bytes(blob), dtype=np.float32).astype(np.float32, copy=True)
        norm = float(np.linalg.norm(value))
        if value.size == 0 or norm <= 1e-9:
            return None
        return value / norm
    except Exception:
        return None


def _cosine(a: Any, b: Any) -> float:
    return float(a @ b)


def _reservoir_add(bucket: list[dict[str, Any]], row: dict[str, Any], seen: int, limit: int, rng: random.Random) -> None:
    if len(bucket) < limit:
        bucket.append(row)
        return
    index = rng.randrange(seen)
    if index < limit:
        bucket[index] = row


def _pair_diagnostics(samples: list[dict[str, Any]], pair_limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prepared: list[dict[str, Any]] = []
    for sample in samples:
        vector = _vector(sample.get("embedding"))
        person_id = sample.get("person_id")
        if vector is None or person_id is None:
            continue
        item = dict(sample)
        item["vector"] = vector
        prepared.append(item)

    per_sample: list[dict[str, Any]] = []
    for index, current in enumerate(prepared):
        best_same: tuple[float, dict[str, Any]] | None = None
        best_other: tuple[float, dict[str, Any]] | None = None
        for other_index, other in enumerate(prepared):
            if index == other_index:
                continue
            score = _cosine(current["vector"], other["vector"])
            target = best_same if int(current["person_id"]) == int(other["person_id"]) else best_other
            if target is None or score > target[0]:
                if int(current["person_id"]) == int(other["person_id"]):
                    best_same = (score, other)
                else:
                    best_other = (score, other)
        same_score = best_same[0] if best_same else None
        other_score = best_other[0] if best_other else None
        per_sample.append({
            "sample_id": current.get("id"),
            "event_id": current.get("event_id"),
            "person_id": current.get("person_id"),
            "quality": current.get("quality"),
            "source": current.get("source", "face"),
            "nearest_same_score": same_score,
            "nearest_same_sample_id": best_same[1].get("id") if best_same else None,
            "nearest_other_score": other_score,
            "nearest_other_sample_id": best_other[1].get("id") if best_other else None,
            "nearest_other_person_id": best_other[1].get("person_id") if best_other else None,
            "same_minus_other_margin": (same_score - other_score) if same_score is not None and other_score is not None else None,
            "suspect_label": bool(same_score is not None and other_score is not None and other_score > same_score),
        })

    rng = random.Random(42)
    same_pairs: list[dict[str, Any]] = []
    other_pairs: list[dict[str, Any]] = []
    same_seen = 0
    other_seen = 0
    half = max(1, pair_limit // 2)
    for left in range(len(prepared)):
        a = prepared[left]
        for right in range(left + 1, len(prepared)):
            b = prepared[right]
            same = int(a["person_id"]) == int(b["person_id"])
            row = {
                "sample_a": a.get("id"),
                "event_a": a.get("event_id"),
                "person_a": a.get("person_id"),
                "quality_a": a.get("quality"),
                "source_a": a.get("source", "face"),
                "sample_b": b.get("id"),
                "event_b": b.get("event_id"),
                "person_b": b.get("person_id"),
                "quality_b": b.get("quality"),
                "source_b": b.get("source", "face"),
                "same_person": int(same),
                "similarity": _cosine(a["vector"], b["vector"]),
            }
            if same:
                same_seen += 1
                _reservoir_add(same_pairs, row, same_seen, half, rng)
            else:
                other_seen += 1
                _reservoir_add(other_pairs, row, other_seen, half, rng)
    return per_sample, same_pairs + other_pairs


def _build_zip(days: int, max_samples: int, pair_limit: int) -> bytes:
    from .config import (
        APP_VERSION,
        BODY_REID_MARGIN,
        BODY_REID_THRESHOLD,
        IDENTITY_CLUSTER_THRESHOLD,
        IDENTITY_KNOWN_THRESHOLD,
    )
    from .db import connection, utc_now

    days = max(1, min(3650, int(days)))
    max_samples = max(20, min(2000, int(max_samples)))
    pair_limit = max(100, min(100000, int(pair_limit)))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with connection() as conn:
        persons = [dict(row) for row in conn.execute(
            "SELECT id, name, created_at, updated_at FROM persons ORDER BY id"
        ).fetchall()]
        events = [dict(row) for row in conn.execute(
            """SELECT id, camera_id, track_id, person_id, probable_person_id,
                body_confidence, body_identity_source, unknown_cluster_id,
                identity_state, identity_confidence, event_type, has_face,
                face_count, confidence, bbox_json, created_at
            FROM events WHERE created_at >= ? ORDER BY created_at DESC LIMIT 5000""",
            (cutoff,),
        ).fetchall()]
        faces = [dict(row) for row in conn.execute(
            """SELECT id, event_id, camera_id, person_id, cluster_id, embedding,
                quality, created_at, 'face' AS source
            FROM face_samples
            WHERE person_id IS NOT NULL
            ORDER BY quality DESC, created_at DESC LIMIT ?""",
            (max_samples,),
        ).fetchall()]
        bodies = [dict(row) for row in conn.execute(
            """SELECT id, event_id, camera_id, person_id, embedding, quality,
                source, verified, created_at, updated_at
            FROM body_samples
            WHERE verified = 1 AND person_id IS NOT NULL
            ORDER BY quality DESC, created_at DESC LIMIT ?""",
            (max_samples,),
        ).fetchall()]
        negatives = [dict(row) for row in conn.execute(
            """SELECT id, event_id, camera_id, quality, created_at
            FROM body_negative_samples ORDER BY created_at DESC LIMIT 1000"""
        ).fetchall()]

    face_samples, face_pairs = _pair_diagnostics(faces, pair_limit)
    body_samples, body_pairs = _pair_diagnostics(bodies, pair_limit)

    manifest = {
        "format": "PersonOfInterest identity calibration diagnostic v1",
        "generated_at": utc_now(),
        "app_version": APP_VERSION,
        "scope": {"days": days, "max_samples_per_modality": max_samples, "pair_limit": pair_limit},
        "counts": {
            "persons": len(persons),
            "events": len(events),
            "face_samples_analyzed": len(face_samples),
            "body_samples_analyzed": len(body_samples),
            "face_pairs": len(face_pairs),
            "body_pairs": len(body_pairs),
            "hard_negative_metadata": len(negatives),
        },
        "thresholds": {
            "face_known": IDENTITY_KNOWN_THRESHOLD,
            "face_cluster": IDENTITY_CLUSTER_THRESHOLD,
            "body_probable": BODY_REID_THRESHOLD,
            "body_margin": BODY_REID_MARGIN,
        },
        "privacy": {
            "raw_face_embeddings_included": False,
            "raw_body_embeddings_included": False,
            "images_included": False,
            "camera_connection_data_included": False,
            "notes": "O pacote contém nomes cadastrados, IDs, metadados de eventos e similaridades derivadas para calibração.",
        },
    }

    sample_fields = [
        "sample_id", "event_id", "person_id", "quality", "source",
        "nearest_same_score", "nearest_same_sample_id", "nearest_other_score",
        "nearest_other_sample_id", "nearest_other_person_id", "same_minus_other_margin",
        "suspect_label",
    ]
    pair_fields = [
        "sample_a", "event_a", "person_a", "quality_a", "source_a",
        "sample_b", "event_b", "person_b", "quality_b", "source_b",
        "same_person", "similarity",
    ]
    event_fields = [
        "id", "camera_id", "track_id", "person_id", "probable_person_id",
        "body_confidence", "body_identity_source", "unknown_cluster_id",
        "identity_state", "identity_confidence", "event_type", "has_face",
        "face_count", "confidence", "bbox_json", "created_at",
    ]
    person_fields = ["id", "name", "created_at", "updated_at"]
    negative_fields = ["id", "event_id", "camera_id", "quality", "created_at"]

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("persons.csv", _csv_text(persons, person_fields))
        archive.writestr("events.csv", _csv_text(events, event_fields))
        archive.writestr("face_samples_analysis.csv", _csv_text(face_samples, sample_fields))
        archive.writestr("face_similarity_pairs.csv", _csv_text(face_pairs, pair_fields))
        archive.writestr("body_samples_analysis.csv", _csv_text(body_samples, sample_fields))
        archive.writestr("body_similarity_pairs.csv", _csv_text(body_pairs, pair_fields))
        archive.writestr("body_negative_metadata.csv", _csv_text(negatives, negative_fields))
    return output.getvalue()


def install() -> None:
    from fastapi import HTTPException
    from fastapi.responses import Response

    from .api_v34 import router

    if getattr(router, "_poi_identity_diagnostics_patch", False):
        return

    def export_identity_diagnostics(
        days: int = 30,
        max_samples: int = 500,
        pair_limit: int = 50000,
    ) -> Response:
        try:
            payload = _build_zip(days, max_samples, pair_limit)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Falha ao gerar diagnóstico: {exc}") from exc
        filename = f"identity_diagnostic_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.zip"
        return Response(
            content=payload,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    router.add_api_route(
        "/api/identity/diagnostics/export",
        export_identity_diagnostics,
        methods=["GET"],
        include_in_schema=True,
        name="export_identity_diagnostics",
    )
    router._poi_identity_diagnostics_patch = True

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any

from . import body_identity as bi
from .config import DATA_DIR, EVENTS_DIR
from .db import connection, utc_now


PROTOTYPE_DIR = DATA_DIR / "false_positive_prototypes"
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False

# Conservative defaults. User-configurable limits are read from storage_settings
# when that table exists.
DEFAULT_MAX_PROTOTYPES_PER_CAMERA = 100
DEFAULT_MAX_EXAMPLES_PER_PROTOTYPE = 5
MERGE_STRONG_SIMILARITY = 0.965
MERGE_SIMILARITY = 0.92
MERGE_BBOX_IOU = 0.35
RETRO_STRONG_SIMILARITY = 0.985
RETRO_SIMILARITY = 0.94
RETRO_BBOX_IOU = 0.50


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        PROTOTYPE_DIR.mkdir(parents=True, exist_ok=True)
        with connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS false_positive_prototypes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id INTEGER NOT NULL,
                    centroid_embedding BLOB NOT NULL,
                    bbox_json TEXT,
                    quality REAL NOT NULL DEFAULT 0,
                    support_count INTEGER NOT NULL DEFAULT 1,
                    representative_path TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_fp_prototypes_camera_active
                    ON false_positive_prototypes(camera_id, active, last_seen DESC);

                CREATE TABLE IF NOT EXISTS false_positive_prototype_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prototype_id INTEGER NOT NULL,
                    source_event_id INTEGER UNIQUE,
                    embedding BLOB NOT NULL,
                    bbox_json TEXT,
                    quality REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(prototype_id) REFERENCES false_positive_prototypes(id) ON DELETE CASCADE,
                    FOREIGN KEY(source_event_id) REFERENCES events(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fp_members_prototype_quality
                    ON false_positive_prototype_members(prototype_id, quality DESC, created_at DESC);
                """
            )
            conn.commit()
        _SCHEMA_READY = True


def _limits() -> tuple[int, int]:
    max_prototypes = DEFAULT_MAX_PROTOTYPES_PER_CAMERA
    max_examples = DEFAULT_MAX_EXAMPLES_PER_PROTOTYPE
    try:
        with connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='storage_settings'"
            ).fetchone()
            if exists:
                row = conn.execute(
                    "SELECT false_positive_max_prototypes_per_camera, false_positive_examples_per_prototype "
                    "FROM storage_settings WHERE id = 1"
                ).fetchone()
                if row:
                    max_prototypes = max(1, int(row[0] or max_prototypes))
                    max_examples = max(1, int(row[1] or max_examples))
    except Exception:
        pass
    return max_prototypes, max_examples


def _vector(blob: bytes | memoryview | None) -> Any | None:
    return bi._blob_to_vector(blob)


def _blob(vector: Any) -> bytes:
    return bi._vector_to_blob(vector)


def _cosine(a: Any, b: Any) -> float:
    return bi._cosine(a, b)


def _bbox_iou(a: str | None, b: str | None) -> float:
    try:
        return float(bi._bbox_iou(a, b))
    except Exception:
        return 0.0


def _safe_event_path(relative: str | None) -> Path | None:
    if not relative:
        return None
    path = (EVENTS_DIR / relative).resolve()
    root = EVENTS_DIR.resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def _representative_filename(prototype_id: int) -> str:
    return f"prototype_{int(prototype_id)}.jpg"


def _copy_representative(prototype_id: int, snapshot_relative: str | None) -> str | None:
    source = _safe_event_path(snapshot_relative)
    if source is None:
        return None
    PROTOTYPE_DIR.mkdir(parents=True, exist_ok=True)
    name = _representative_filename(prototype_id)
    target = (PROTOTYPE_DIR / name).resolve()
    if PROTOTYPE_DIR.resolve() not in target.parents:
        return None
    try:
        shutil.copy2(source, target)
        return name
    except OSError:
        return None


def prototype_image_path(prototype_id: int) -> Path | None:
    ensure_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT representative_path FROM false_positive_prototypes WHERE id = ?",
            (int(prototype_id),),
        ).fetchone()
    if row is None or not row[0]:
        return None
    path = (PROTOTYPE_DIR / str(row[0])).resolve()
    if PROTOTYPE_DIR.resolve() not in path.parents or not path.is_file():
        return None
    return path


def _prototype_rows(camera_id: int, *, active_only: bool = True) -> list[dict[str, Any]]:
    ensure_schema()
    sql = "SELECT * FROM false_positive_prototypes WHERE camera_id = ?"
    params: list[Any] = [int(camera_id)]
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY last_seen DESC, id DESC"
    with connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def negative_gallery(camera_id: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in _prototype_rows(camera_id, active_only=True):
        output.append(
            {
                "embedding": row["centroid_embedding"],
                "quality": float(row.get("quality") or 0.0),
                "bbox_json": row.get("bbox_json"),
                "prototype_id": int(row["id"]),
                "persistent": True,
            }
        )
    return output


def _recompute_prototype(prototype_id: int) -> None:
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT embedding, bbox_json, quality, created_at
            FROM false_positive_prototype_members
            WHERE prototype_id = ? ORDER BY quality DESC, created_at DESC""",
            (int(prototype_id),),
        ).fetchall()
        if not rows:
            conn.execute(
                "UPDATE false_positive_prototypes SET active = 0, support_count = 0, updated_at = ? WHERE id = ?",
                (utc_now(), int(prototype_id)),
            )
            conn.commit()
            return

        vectors: list[Any] = []
        weights: list[float] = []
        for row in rows:
            vector = _vector(row["embedding"])
            if vector is None:
                continue
            vectors.append(vector)
            weights.append(max(0.10, float(row["quality"] or 0.0)))
        if not vectors or bi.np is None:
            return
        matrix = bi.np.stack(vectors, axis=0)
        w = bi.np.asarray(weights, dtype=bi.np.float32)
        centroid = bi._normalize((matrix * w[:, None]).sum(axis=0))
        best = rows[0]
        first_seen = min(str(row["created_at"]) for row in rows)
        last_seen = max(str(row["created_at"]) for row in rows)
        conn.execute(
            """UPDATE false_positive_prototypes
            SET centroid_embedding = ?, bbox_json = ?, quality = ?, support_count = ?,
                active = 1, first_seen = ?, last_seen = ?, updated_at = ?
            WHERE id = ?""",
            (
                _blob(centroid),
                best["bbox_json"],
                float(best["quality"] or 0.0),
                len(rows),
                first_seen,
                last_seen,
                utc_now(),
                int(prototype_id),
            ),
        )
        conn.commit()


def _prune_members(prototype_id: int) -> None:
    _, max_examples = _limits()
    with connection() as conn:
        rows = conn.execute(
            """SELECT id FROM false_positive_prototype_members
            WHERE prototype_id = ?
            ORDER BY quality DESC, created_at DESC""",
            (int(prototype_id),),
        ).fetchall()
        extra = [int(row[0]) for row in rows[max_examples:]]
        if extra:
            marks = ",".join("?" for _ in extra)
            conn.execute(f"DELETE FROM false_positive_prototype_members WHERE id IN ({marks})", extra)
            conn.commit()
    if extra:
        _recompute_prototype(prototype_id)


def _prune_prototypes(camera_id: int) -> None:
    max_prototypes, _ = _limits()
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, representative_path FROM false_positive_prototypes
            WHERE camera_id = ?
            ORDER BY active DESC, support_count DESC, last_seen DESC, id DESC""",
            (int(camera_id),),
        ).fetchall()
        extras = rows[max_prototypes:]
        for row in extras:
            conn.execute("DELETE FROM false_positive_prototypes WHERE id = ?", (int(row["id"]),))
        if extras:
            conn.commit()
    for row in extras:
        if row["representative_path"]:
            path = (PROTOTYPE_DIR / str(row["representative_path"])).resolve()
            if PROTOTYPE_DIR.resolve() in path.parents:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def _choose_prototype(camera_id: int, embedding: Any, bbox_json: str | None) -> int | None:
    best_id: int | None = None
    best_score = -1.0
    for row in _prototype_rows(camera_id, active_only=True):
        candidate = _vector(row.get("centroid_embedding"))
        if candidate is None:
            continue
        score = _cosine(embedding, candidate)
        iou = _bbox_iou(bbox_json, row.get("bbox_json"))
        if score >= MERGE_STRONG_SIMILARITY or (score >= MERGE_SIMILARITY and iou >= MERGE_BBOX_IOU):
            if score > best_score:
                best_score = score
                best_id = int(row["id"])
    return best_id


def learn_event(event_id: int, *, propagate: bool = True, body_manager: Any | None = None) -> dict[str, Any]:
    """Persist one *manual* false-positive example independently of the event.

    The member embedding survives Timeline retention because source_event_id uses
    ON DELETE SET NULL. Automatic matches never update the centroid, preventing
    self-reinforcing drift.
    """
    ensure_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT e.id, e.camera_id, e.bbox_json, e.snapshot_path, e.created_at,
                bs.embedding, bs.quality
            FROM events e
            LEFT JOIN body_samples bs ON bs.event_id = e.id
            WHERE e.id = ?""",
            (int(event_id),),
        ).fetchone()
    if row is None or not row["embedding"]:
        return {"learned": False, "reason": "embedding_unavailable", "event_id": int(event_id)}
    embedding = _vector(row["embedding"])
    if embedding is None:
        return {"learned": False, "reason": "embedding_invalid", "event_id": int(event_id)}

    camera_id = int(row["camera_id"])
    bbox_json = str(row["bbox_json"] or "")
    quality = float(row["quality"] or 0.0)
    prototype_id = _choose_prototype(camera_id, embedding, bbox_json)
    now = utc_now()

    with connection() as conn:
        if prototype_id is None:
            cursor = conn.execute(
                """INSERT INTO false_positive_prototypes(
                    camera_id, centroid_embedding, bbox_json, quality, support_count,
                    active, first_seen, last_seen, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?, ?)""",
                (
                    camera_id,
                    _blob(embedding),
                    bbox_json,
                    quality,
                    str(row["created_at"] or now),
                    str(row["created_at"] or now),
                    now,
                    now,
                ),
            )
            prototype_id = int(cursor.lastrowid)
        conn.execute(
            """INSERT INTO false_positive_prototype_members(
                prototype_id, source_event_id, embedding, bbox_json, quality, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_event_id) DO UPDATE SET
                prototype_id = excluded.prototype_id,
                embedding = excluded.embedding,
                bbox_json = excluded.bbox_json,
                quality = excluded.quality,
                created_at = excluded.created_at""",
            (prototype_id, int(event_id), _blob(embedding), bbox_json, quality, now),
        )
        conn.commit()

    _prune_members(prototype_id)
    _recompute_prototype(prototype_id)

    with connection() as conn:
        proto = conn.execute(
            "SELECT quality, representative_path FROM false_positive_prototypes WHERE id = ?",
            (prototype_id,),
        ).fetchone()
    if proto is not None and (not proto["representative_path"] or quality >= float(proto["quality"] or 0.0)):
        representative = _copy_representative(prototype_id, row["snapshot_path"])
        if representative:
            with connection() as conn:
                conn.execute(
                    "UPDATE false_positive_prototypes SET representative_path = ?, updated_at = ? WHERE id = ?",
                    (representative, utc_now(), prototype_id),
                )
                conn.commit()

    _prune_prototypes(camera_id)
    propagated = 0
    if propagate and body_manager is not None:
        propagated = propagate_prototype(prototype_id, body_manager)
    return {
        "learned": True,
        "event_id": int(event_id),
        "prototype_id": int(prototype_id),
        "propagated": int(propagated),
    }


def propagate_prototype(prototype_id: int, body_manager: Any) -> int:
    """Retroactively suppress only extremely strong, face-free matches."""
    ensure_schema()
    with connection() as conn:
        proto = conn.execute(
            "SELECT * FROM false_positive_prototypes WHERE id = ? AND active = 1",
            (int(prototype_id),),
        ).fetchone()
        if proto is None:
            return 0
        rows = conn.execute(
            """SELECT e.id, e.bbox_json, bs.embedding, bs.quality
            FROM events e
            JOIN body_samples bs ON bs.event_id = e.id
            WHERE e.camera_id = ?
              AND e.person_id IS NULL
              AND COALESCE(e.identity_state, '') <> 'false_positive'
              AND COALESCE(e.has_face, 0) = 0
              AND COALESCE(e.identity_origin, 'vision') NOT LIKE 'manual%'
            ORDER BY e.created_at DESC""",
            (int(proto["camera_id"]),),
        ).fetchall()
    centroid = _vector(proto["centroid_embedding"])
    if centroid is None:
        return 0
    changed = 0
    for row in rows:
        candidate = _vector(row["embedding"])
        if candidate is None:
            continue
        score = _cosine(centroid, candidate)
        iou = _bbox_iou(str(proto["bbox_json"] or ""), str(row["bbox_json"] or ""))
        if score >= RETRO_STRONG_SIMILARITY or (score >= RETRO_SIMILARITY and iou >= RETRO_BBOX_IOU):
            try:
                body_manager._mark_auto_false_positive(int(row["id"]), float(score))
                changed += 1
            except Exception:
                continue
    return changed


def forget_event(event_id: int) -> None:
    """Remove a manual example from the learned prototype without touching others."""
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            "SELECT prototype_id FROM false_positive_prototype_members WHERE source_event_id = ?",
            (int(event_id),),
        ).fetchall()
        prototype_ids = [int(row[0]) for row in rows]
        conn.execute(
            "DELETE FROM false_positive_prototype_members WHERE source_event_id = ?",
            (int(event_id),),
        )
        conn.commit()
    for prototype_id in prototype_ids:
        _recompute_prototype(prototype_id)


def deactivate_prototype(prototype_id: int) -> bool:
    ensure_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM false_positive_prototypes WHERE id = ?",
            (int(prototype_id),),
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "UPDATE false_positive_prototypes SET active = 0, updated_at = ? WHERE id = ?",
            (utc_now(), int(prototype_id)),
        )
        conn.commit()
    return True


def activate_prototype(prototype_id: int) -> bool:
    ensure_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM false_positive_prototypes WHERE id = ?",
            (int(prototype_id),),
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "UPDATE false_positive_prototypes SET active = 1, updated_at = ? WHERE id = ?",
            (utc_now(), int(prototype_id)),
        )
        conn.commit()
    return True


def list_prototypes() -> list[dict[str, Any]]:
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT fp.id, fp.camera_id, c.name AS camera_name, fp.quality,
                fp.support_count, fp.representative_path, fp.active, fp.first_seen,
                fp.last_seen, fp.created_at, fp.updated_at
            FROM false_positive_prototypes fp
            JOIN cameras c ON c.id = fp.camera_id
            ORDER BY fp.active DESC, fp.last_seen DESC, fp.id DESC"""
        ).fetchall()
    return [
        {
            **dict(row),
            "active": bool(row["active"]),
            "image_url": f"/api/false-positives/prototypes/{int(row['id'])}/image" if row["representative_path"] else None,
        }
        for row in rows
    ]


def backfill_existing(body_manager: Any | None = None) -> dict[str, int]:
    """Consolidate historical *manual* negatives into bounded prototypes."""
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT e.id
            FROM events e
            JOIN body_samples bs ON bs.event_id = e.id
            WHERE e.identity_state = 'false_positive'
              AND bs.source = 'false_positive'
            ORDER BY e.created_at ASC"""
        ).fetchall()
    learned = 0
    for row in rows:
        result = learn_event(int(row["id"]), propagate=False)
        if result.get("learned"):
            learned += 1
    propagated = 0
    if body_manager is not None:
        with connection() as conn:
            ids = [
                int(row[0])
                for row in conn.execute(
                    "SELECT id FROM false_positive_prototypes WHERE active = 1 ORDER BY id"
                ).fetchall()
            ]
        for prototype_id in ids:
            propagated += propagate_prototype(prototype_id, body_manager)
    return {"learned": learned, "propagated": propagated}

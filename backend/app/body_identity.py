from __future__ import annotations

import json
import math
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import (
    BODY_NEGATIVE_BBOX_IOU,
    BODY_NEGATIVE_MARGIN,
    BODY_NEGATIVE_MIN_QUALITY,
    BODY_NEGATIVE_MIN_SUPPORT,
    BODY_NEGATIVE_SINGLE_THRESHOLD,
    BODY_NEGATIVE_THRESHOLD,
    BODY_REID_FACE_BONUS,
    BODY_REID_MARGIN,
    BODY_REID_MODEL_PATH,
    BODY_REID_POLL_SECONDS,
    BODY_REID_THRESHOLD,
    EVENTS_DIR,
    FACES_DIR,
)
from .db import connection, utc_now

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    import onnxruntime as ort  # type: ignore
    RUNTIME_AVAILABLE = True
    RUNTIME_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - optional runtime boundary
    cv2 = None  # type: ignore
    np = None  # type: ignore
    ort = None  # type: ignore
    RUNTIME_AVAILABLE = False
    RUNTIME_ERROR = str(exc)


def _normalize(vector: Any) -> Any:
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-9:
        return vector
    return vector / norm


def _vector_to_blob(vector: Any) -> bytes:
    return np.asarray(vector, dtype=np.float32).reshape(-1).tobytes()


def _blob_to_vector(blob: bytes | memoryview | None) -> Any | None:
    if not blob or np is None:
        return None
    vector = np.frombuffer(bytes(blob), dtype=np.float32).astype(np.float32, copy=True)
    if vector.size == 0:
        return None
    return _normalize(vector)


def _cosine(a: Any, b: Any) -> float:
    return float(np.dot(a, b))


def _event_path(relative: str | None) -> Path | None:
    if not relative:
        return None
    path = (EVENTS_DIR / relative).resolve()
    root = EVENTS_DIR.resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def _face_path(relative: str | None) -> Path | None:
    if not relative:
        return None
    path = (FACES_DIR / relative).resolve()
    root = FACES_DIR.resolve()
    if root not in path.parents:
        return None
    return path


def _source_bonus(source: str | None) -> float:
    # Body is never an absolute identity signal. A body sample that was observed
    # in the same event as a confirmed face is simply a stronger ReID reference.
    return BODY_REID_FACE_BONUS if (source or "").startswith("face_verified") else 0.0


def _bbox_tuple(raw: str | None) -> tuple[float, float, float, float] | None:
    if not raw:
        return None
    try:
        box = json.loads(raw)
        x = float(box.get("x", 0))
        y = float(box.get("y", 0))
        w = float(box.get("w", 0))
        h = float(box.get("h", 0))
        if w <= 0 or h <= 0:
            return None
        return x, y, w, h
    except Exception:
        return None


def _bbox_iou(a_raw: str | None, b_raw: str | None) -> float:
    a = _bbox_tuple(a_raw)
    b = _bbox_tuple(b_raw)
    if a is None or b is None:
        return 0.0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 1e-9 else 0.0


def _best_positive_body_score(query: Any, query_quality: float, gallery: list[dict[str, Any]]) -> float:
    best = -1.0
    query_factor = 0.90 + 0.10 * max(0.0, min(1.0, query_quality))
    for item in gallery:
        candidate = _blob_to_vector(item.get("embedding"))
        if candidate is None:
            continue
        quality = max(0.0, min(1.0, float(item.get("quality") or 0.0)))
        score = _cosine(query, candidate) * (0.88 + 0.12 * quality)
        score += _source_bonus(item.get("source"))
        best = max(best, score * query_factor)
    return best


def rank_hard_negative(
    query: Any,
    query_quality: float,
    negatives: list[dict[str, Any]],
    positive_gallery: list[dict[str, Any]] | None = None,
    query_bbox_json: str | None = None,
) -> tuple[bool, float | None, str | None]:
    """Decide whether a detection strongly matches reviewed false positives.

    This is deliberately conservative. Two supporting manual negatives are the
    normal path. A single example may reject only at very high appearance
    similarity plus strong bounding-box overlap, which is useful for stationary
    objects repeatedly mistaken for people. Verified human body references can
    veto a weak/ambiguous negative match.
    """
    query_factor = 0.90 + 0.10 * max(0.0, min(1.0, query_quality))
    scored: list[tuple[float, float]] = []
    for item in negatives:
        candidate = _blob_to_vector(item.get("embedding"))
        if candidate is None:
            continue
        reference_quality = max(0.0, min(1.0, float(item.get("quality") or 0.0)))
        score = _cosine(query, candidate) * (0.90 + 0.10 * reference_quality) * query_factor
        scored.append((score, _bbox_iou(query_bbox_json, item.get("bbox_json"))))

    if not scored:
        return False, None, None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    top = scored[:3]
    best_score, best_iou = top[0]
    support = sum(1 for score, _ in scored if score >= BODY_NEGATIVE_THRESHOLD - 0.035)
    mean_top = sum(score for score, _ in top) / len(top)
    aggregate = 0.74 * best_score + 0.26 * mean_top

    positive_best = _best_positive_body_score(query, query_quality, positive_gallery or [])
    if positive_best >= BODY_REID_THRESHOLD and aggregate < positive_best + BODY_NEGATIVE_MARGIN:
        return False, aggregate, "human_reference_wins"

    if support >= max(2, BODY_NEGATIVE_MIN_SUPPORT) and aggregate >= BODY_NEGATIVE_THRESHOLD:
        return True, min(0.999, aggregate), "repeated_reviewed_negative"

    if best_score >= BODY_NEGATIVE_SINGLE_THRESHOLD and best_iou >= BODY_NEGATIVE_BBOX_IOU:
        if positive_best < BODY_REID_THRESHOLD or best_score >= positive_best + BODY_NEGATIVE_MARGIN:
            return True, min(0.999, best_score), "stationary_reviewed_negative"

    return False, min(0.999, aggregate), "insufficient_negative_evidence"


def rank_probable(
    query: Any,
    query_quality: float,
    gallery: list[dict[str, Any]],
) -> tuple[int | None, float | None, str | None]:
    """Return a probable person from verified body references.

    Face-linked references receive a small scoring bonus, but this function
    intentionally never returns an absolute identity. Callers persist the
    result in probable_person_id, not person_id.
    """
    per_person: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for item in gallery:
        candidate = _blob_to_vector(item.get("embedding"))
        if candidate is None:
            continue
        similarity = _cosine(query, candidate)
        reference_quality = max(0.0, min(1.0, float(item.get("quality") or 0.0)))
        similarity *= 0.88 + 0.12 * reference_quality
        face_linked = str(item.get("source") or "").startswith("face_verified")
        similarity += _source_bonus(item.get("source"))
        per_person[int(item["person_id"])].append((similarity, face_linked))

    ranked: list[tuple[float, int, bool]] = []
    query_factor = 0.90 + 0.10 * max(0.0, min(1.0, query_quality))
    for person_id, values in per_person.items():
        ordered = sorted(values, key=lambda pair: pair[0], reverse=True)[:3]
        best = ordered[0][0]
        mean = sum(value for value, _ in ordered) / len(ordered)
        score = (0.76 * best + 0.24 * mean) * query_factor
        ranked.append((score, person_id, any(face_linked for _, face_linked in ordered)))

    if not ranked:
        return None, None, None
    ranked.sort(reverse=True)
    best_score, best_person, face_linked = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else -1.0
    if best_score < BODY_REID_THRESHOLD or best_score - second_score < BODY_REID_MARGIN:
        return None, None, None
    source = "face_linked_body" if face_linked else "body_reid"
    return best_person, max(0.0, min(0.99, best_score)), source


class BodyIdentityManager:
    """Appearance ReID that can only produce *probable* identities.

    Absolute identity remains owned by face/manual confirmation. Body embeddings
    are useful when a face is not visible, but they are deliberately persisted
    in separate probable_* fields to avoid silently upgrading clothes/appearance
    into a facial identity claim.
    """

    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()
        self.status = "stopped"
        self.error: str | None = None
        self._session: Any | None = None
        self._input_name = ""
        self._nchw = True
        self._batch_size = 1

    @property
    def available(self) -> bool:
        return RUNTIME_AVAILABLE and BODY_REID_MODEL_PATH.is_file()

    def _ensure_aux_schema(self) -> None:
        with connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS body_negative_exemptions (
                    event_id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_body_negative_exemptions_created
                    ON body_negative_exemptions(created_at DESC);
                """
            )
            conn.commit()

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self._ensure_aux_schema()
            self.stop_event.clear()
            self.wake_event.clear()
            self.thread = threading.Thread(target=self._run, name="poi-body-reid", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.5)

    def notify_change(self) -> None:
        self.wake_event.set()

    def _ensure_model(self) -> None:
        if not RUNTIME_AVAILABLE:
            raise RuntimeError(RUNTIME_ERROR or "ONNX Runtime indisponível")
        if not BODY_REID_MODEL_PATH.is_file():
            raise RuntimeError(f"OSNet não encontrado: {BODY_REID_MODEL_PATH}")
        if self._session is not None:
            return
        self._session = ort.InferenceSession(str(BODY_REID_MODEL_PATH), providers=["CPUExecutionProvider"])
        input_meta = self._session.get_inputs()[0]
        self._input_name = input_meta.name
        shape = list(input_meta.shape)
        self._nchw = not (len(shape) == 4 and shape[-1] == 3)
        first_dim = shape[0] if shape else 1
        self._batch_size = int(first_dim) if isinstance(first_dim, int) and first_dim > 0 else 1

    def _run(self) -> None:  # pragma: no cover - background integration
        self.status = "starting"
        try:
            self._ensure_model()
            self._ensure_aux_schema()
            self.status = "running"
            self.error = None
        except Exception as exc:
            self.status = "unavailable"
            self.error = str(exc)
            return

        while not self.stop_event.is_set():
            try:
                self._sync_verified_labels()
                backfilled = self._backfill_hard_negatives(4)
                processed = self.process_pending_once(6)
                self._refresh_probables(100)
                self.status = "running"
                self.error = None
                delay = 0.15 if (processed or backfilled) else max(0.35, BODY_REID_POLL_SECONDS)
            except sqlite3.OperationalError:
                delay = 0.8
            except Exception as exc:
                self.status = "error"
                self.error = str(exc)
                delay = 2.0
            self.wake_event.wait(delay)
            self.wake_event.clear()

    def state(self) -> dict[str, Any]:
        try:
            self._ensure_aux_schema()
            with connection() as conn:
                samples = int(conn.execute("SELECT COUNT(*) FROM body_samples").fetchone()[0])
                verified = int(conn.execute("SELECT COUNT(*) FROM body_samples WHERE verified = 1 AND person_id IS NOT NULL").fetchone()[0])
                probable = int(conn.execute("SELECT COUNT(*) FROM events WHERE person_id IS NULL AND probable_person_id IS NOT NULL").fetchone()[0])
                negatives = int(conn.execute("SELECT COUNT(*) FROM body_negative_samples").fetchone()[0])
                auto_false = int(conn.execute(
                    "SELECT COUNT(*) FROM events WHERE identity_state = 'false_positive' AND body_identity_source = 'hard_negative_auto'"
                ).fetchone()[0])
        except Exception:
            samples = verified = probable = negatives = auto_false = 0
        return {
            "status": self.status,
            "error": self.error,
            "available": self.available,
            "samples": samples,
            "verified_samples": verified,
            "probable_events": probable,
            "hard_negatives": negatives,
            "auto_false_positives": auto_false,
            "threshold": BODY_REID_THRESHOLD,
            "margin": BODY_REID_MARGIN,
            "negative_threshold": BODY_NEGATIVE_THRESHOLD,
            "negative_single_threshold": BODY_NEGATIVE_SINGLE_THRESHOLD,
            "negative_margin": BODY_NEGATIVE_MARGIN,
            "negative_min_support": BODY_NEGATIVE_MIN_SUPPORT,
        }

    def _load_event_crop(self, event: dict[str, Any]) -> tuple[Any, float] | None:
        path = _event_path(event.get("snapshot_path"))
        if path is None:
            return None
        frame = cv2.imread(str(path))
        if frame is None:
            return None
        height, width = frame.shape[:2]
        try:
            bbox = json.loads(event.get("bbox_json") or "{}")
            x = int(float(bbox.get("x", 0)))
            y = int(float(bbox.get("y", 0)))
            w = int(float(bbox.get("w", 0)))
            h = int(float(bbox.get("h", 0)))
        except Exception:
            return None
        if w < 18 or h < 36:
            return None
        x1 = max(0, x + 2)
        y1 = max(0, y + 2)
        x2 = min(width, x + w - 2)
        y2 = min(height, y + h - 2)
        if x2 - x1 < 16 or y2 - y1 < 32:
            return None
        crop = frame[y1:y2, x1:x2]
        area_ratio = ((x2 - x1) * (y2 - y1)) / max(1.0, float(width * height))
        size_quality = min(1.0, math.sqrt(max(0.0, area_ratio) / 0.16))
        touches_edge = x <= 2 or y <= 2 or x + w >= width - 2 or y + h >= height - 2
        edge_factor = 0.72 if touches_edge else 1.0
        detection = max(0.0, min(1.0, float(event.get("confidence") or 0.5)))
        quality = max(0.15, min(1.0, (0.55 * detection + 0.45 * size_quality) * edge_factor))
        return crop, quality

    def _embed_crop(self, crop: Any) -> Any:
        self._ensure_model()
        image = cv2.resize(crop, (128, 256), interpolation=cv2.INTER_LINEAR)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
        image = (image - mean) / std
        if self._nchw:
            tensor = np.transpose(image, (2, 0, 1))[None, ...]
        else:
            tensor = image[None, ...]
        if self._batch_size > 1:
            tensor = np.repeat(tensor, self._batch_size, axis=0)
        output = np.asarray(self._session.run(None, {self._input_name: tensor})[0])
        vector = output[0] if output.ndim >= 2 and output.shape[0] == self._batch_size else output
        return _normalize(vector)

    def _event_embedding(self, event: dict[str, Any]) -> tuple[Any, float] | None:
        loaded = self._load_event_crop(event)
        if loaded is None:
            return None
        crop, quality = loaded
        return self._embed_crop(crop), quality

    def _backfill_hard_negatives(self, limit: int = 4) -> int:
        with connection() as conn:
            rows = conn.execute(
                """SELECT e.id FROM events e
                LEFT JOIN body_negative_samples bn ON bn.event_id = e.id
                WHERE e.identity_state = 'false_positive'
                  AND e.snapshot_path IS NOT NULL
                  AND bn.id IS NULL
                  AND COALESCE(e.body_identity_source, '') <> 'hard_negative_auto'
                ORDER BY e.created_at DESC LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()
        count = 0
        for row in rows:
            if self.stop_event.is_set():
                break
            self.record_false_positive(int(row["id"]))
            count += 1
        return count

    def process_pending_once(self, limit: int = 6) -> int:
        with connection() as conn:
            rows = conn.execute(
                """SELECT e.* FROM events e
                LEFT JOIN body_samples bs ON bs.event_id = e.id
                WHERE bs.id IS NULL AND e.snapshot_path IS NOT NULL
                  AND COALESCE(e.identity_state, '') <> 'false_positive'
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

    def _persist_body_sample(self, event: dict[str, Any], embedding: Any, quality: float) -> None:
        with connection() as conn:
            face = conn.execute(
                "SELECT person_id FROM face_samples WHERE event_id = ? AND person_id IS NOT NULL",
                (event["id"],),
            ).fetchone()
            current = conn.execute("SELECT person_id FROM events WHERE id = ?", (event["id"],)).fetchone()
            person_id = current["person_id"] if current else event.get("person_id")
            verified = int(person_id is not None)
            if verified and face and int(face["person_id"]) == int(person_id):
                source = "face_verified"
            elif verified:
                source = "manual_verified"
            else:
                source = "unlabeled"
            now = utc_now()
            conn.execute(
                """INSERT OR REPLACE INTO body_samples(
                    event_id, camera_id, person_id, embedding, quality, source, verified, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["id"], event["camera_id"], person_id,
                    _vector_to_blob(embedding), quality, source, verified, now, now,
                ),
            )
            conn.commit()
        if person_id is None:
            if self._check_hard_negative(int(event["id"]), embedding, quality):
                return
            self._score_event(int(event["id"]), embedding=embedding, quality=quality)

    def _gallery(self) -> list[dict[str, Any]]:
        with connection() as conn:
            rows = conn.execute(
                """SELECT person_id, embedding, quality, source
                FROM body_samples
                WHERE verified = 1 AND person_id IS NOT NULL
                  AND source NOT IN ('false_positive', 'auto_false_positive') AND quality >= 0.38"""
            ).fetchall()
        return [dict(row) for row in rows]

    def _negative_gallery(self, camera_id: int) -> list[dict[str, Any]]:
        with connection() as conn:
            rows = conn.execute(
                """SELECT bn.embedding, bn.quality, e.bbox_json
                FROM body_negative_samples bn
                LEFT JOIN events e ON e.id = bn.event_id
                WHERE bn.camera_id = ? AND bn.quality >= ?
                ORDER BY bn.created_at DESC LIMIT 160""",
                (camera_id, BODY_NEGATIVE_MIN_QUALITY),
            ).fetchall()
        return [dict(row) for row in rows]

    def _check_hard_negative(self, event_id: int, embedding: Any, quality: float) -> bool:
        self._ensure_aux_schema()
        with connection() as conn:
            event = conn.execute(
                "SELECT id, camera_id, person_id, identity_state, bbox_json FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if event is None or event["person_id"] is not None or event["identity_state"] == "false_positive":
                return False
            if conn.execute("SELECT 1 FROM body_negative_exemptions WHERE event_id = ?", (event_id,)).fetchone():
                return False
        negatives = self._negative_gallery(int(event["camera_id"]))
        if not negatives:
            return False
        rejected, score, _ = rank_hard_negative(
            embedding,
            quality,
            negatives,
            self._gallery(),
            str(event["bbox_json"] or ""),
        )
        if not rejected:
            return False
        self._mark_auto_false_positive(event_id, float(score or 0.0))
        return True

    def _mark_auto_false_positive(self, event_id: int, score: float) -> None:
        crops_to_delete: set[str] = set()
        with connection() as conn:
            event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            if event is None or event["person_id"] is not None:
                return
            sample = conn.execute(
                "SELECT cluster_id, crop_path FROM face_samples WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            cluster_id = event["unknown_cluster_id"] or (sample["cluster_id"] if sample else None)

            if cluster_id is not None:
                samples = conn.execute(
                    "SELECT event_id, crop_path FROM face_samples WHERE cluster_id = ?",
                    (cluster_id,),
                ).fetchall()
                crops_to_delete.update(str(row["crop_path"]) for row in samples if row["crop_path"])
                conn.execute("DELETE FROM face_samples WHERE cluster_id = ?", (cluster_id,))
                conn.execute(
                    """UPDATE events
                    SET person_id = NULL, probable_person_id = NULL, body_confidence = NULL,
                        body_identity_source = NULL, unknown_cluster_id = NULL,
                        identity_state = 'pending', identity_confidence = NULL
                    WHERE unknown_cluster_id = ? AND id <> ?
                      AND COALESCE(identity_state, '') <> 'false_positive'""",
                    (cluster_id, event_id),
                )
                conn.execute("DELETE FROM unknown_clusters WHERE id = ?", (cluster_id,))

            current_sample = conn.execute(
                "SELECT crop_path FROM face_samples WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if current_sample and current_sample["crop_path"]:
                crops_to_delete.add(str(current_sample["crop_path"]))
            conn.execute("DELETE FROM face_samples WHERE event_id = ?", (event_id,))
            conn.execute(
                """UPDATE body_samples
                SET person_id = NULL, verified = 0, source = 'auto_false_positive', updated_at = ?
                WHERE event_id = ?""",
                (utc_now(), event_id),
            )
            conn.execute(
                """UPDATE events
                SET person_id = NULL, probable_person_id = NULL, body_confidence = ?,
                    body_identity_source = 'hard_negative_auto', unknown_cluster_id = NULL,
                    identity_state = 'false_positive', identity_confidence = NULL
                WHERE id = ?""",
                (max(0.0, min(0.999, score)), event_id),
            )
            conn.execute(
                "INSERT OR REPLACE INTO alert_event_state(event_id, evaluated_at) VALUES (?, ?)",
                (event_id, utc_now()),
            )
            conn.commit()

        for crop in crops_to_delete:
            path = _face_path(crop)
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _score_event(self, event_id: int, *, embedding: Any | None = None, quality: float | None = None) -> None:
        with connection() as conn:
            event = conn.execute(
                "SELECT id, person_id, identity_state FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if event is None or event["person_id"] is not None or event["identity_state"] == "false_positive":
                if event is not None and event["identity_state"] != "false_positive":
                    conn.execute(
                        "UPDATE events SET probable_person_id = NULL, body_confidence = NULL, body_identity_source = NULL WHERE id = ?",
                        (event_id,),
                    )
                    conn.commit()
                return
            if embedding is None:
                sample = conn.execute(
                    "SELECT embedding, quality FROM body_samples WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if sample is None:
                    return
                embedding = _blob_to_vector(sample["embedding"])
                quality = float(sample["quality"] or 0.0)
        if embedding is None:
            return
        person_id, score, source = rank_probable(embedding, float(quality or 0.0), self._gallery())
        with connection() as conn:
            conn.execute(
                """UPDATE events SET probable_person_id = ?, body_confidence = ?, body_identity_source = ?
                WHERE id = ? AND person_id IS NULL AND COALESCE(identity_state, '') <> 'false_positive'""",
                (person_id, score, source, event_id),
            )
            conn.commit()

    def _refresh_probables(self, limit: int = 100) -> None:
        with connection() as conn:
            rows = conn.execute(
                """SELECT e.id, bs.embedding, bs.quality
                FROM events e JOIN body_samples bs ON bs.event_id = e.id
                WHERE e.person_id IS NULL AND COALESCE(e.identity_state, '') <> 'false_positive'
                ORDER BY e.created_at DESC LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()
        for row in rows:
            embedding = _blob_to_vector(row["embedding"])
            if embedding is None:
                continue
            quality = float(row["quality"] or 0.0)
            if self._check_hard_negative(int(row["id"]), embedding, quality):
                continue
            self._score_event(int(row["id"]), embedding=embedding, quality=quality)

    def _sync_verified_labels(self) -> None:
        with connection() as conn:
            rows = conn.execute(
                """SELECT bs.event_id, bs.person_id sample_person, bs.source, e.person_id event_person,
                    EXISTS(SELECT 1 FROM face_samples fs WHERE fs.event_id = e.id AND fs.person_id = e.person_id) AS face_verified
                FROM body_samples bs JOIN events e ON e.id = bs.event_id
                WHERE COALESCE(e.identity_state, '') <> 'false_positive'"""
            ).fetchall()
            now = utc_now()
            changed = False
            for row in rows:
                event_person = row["event_person"]
                if event_person is None:
                    continue
                desired_source = "face_verified" if row["face_verified"] else "manual_verified"
                if row["sample_person"] != event_person or row["source"] != desired_source:
                    conn.execute(
                        "UPDATE body_samples SET person_id = ?, verified = 1, source = ?, updated_at = ? WHERE event_id = ?",
                        (event_person, desired_source, now, row["event_id"]),
                    )
                    conn.execute(
                        "DELETE FROM body_negative_exemptions WHERE event_id = ?",
                        (row["event_id"],),
                    )
                    conn.execute(
                        "UPDATE events SET probable_person_id = NULL, body_confidence = NULL, body_identity_source = NULL WHERE id = ?",
                        (row["event_id"],),
                    )
                    changed = True
            if changed:
                conn.commit()

    def confirm_event_identity(self, event_id: int, person_id: int) -> None:
        self._ensure_aux_schema()
        with connection() as conn:
            face = conn.execute(
                "SELECT 1 FROM face_samples WHERE event_id = ? AND person_id = ?",
                (event_id, person_id),
            ).fetchone()
            source = "face_verified_manual" if face else "manual_verified"
            conn.execute(
                """UPDATE body_samples SET person_id = ?, verified = 1, source = ?, updated_at = ?
                WHERE event_id = ?""",
                (person_id, source, utc_now(), event_id),
            )
            conn.execute("DELETE FROM body_negative_exemptions WHERE event_id = ?", (event_id,))
            conn.execute(
                "UPDATE events SET probable_person_id = NULL, body_confidence = NULL, body_identity_source = NULL WHERE id = ?",
                (event_id,),
            )
            conn.commit()
        self.notify_change()

    def record_false_positive(self, event_id: int) -> None:
        self._ensure_aux_schema()
        embedding: Any | None = None
        quality = 0.0
        camera_id: int | None = None
        with connection() as conn:
            event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            if event is None:
                return
            camera_id = int(event["camera_id"])
            sample = conn.execute(
                "SELECT embedding, quality FROM body_samples WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if sample:
                embedding = _blob_to_vector(sample["embedding"])
                quality = float(sample["quality"] or 0.0)
        if embedding is None:
            try:
                embedded = self._event_embedding(dict(event))
                if embedded is not None:
                    embedding, quality = embedded
            except Exception as exc:
                self.error = f"Hard-negative não extraído: {exc}"
        with connection() as conn:
            conn.execute("DELETE FROM body_negative_exemptions WHERE event_id = ?", (event_id,))
            if embedding is not None and camera_id is not None:
                conn.execute(
                    """INSERT OR REPLACE INTO body_negative_samples(event_id, camera_id, embedding, quality, created_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (event_id, camera_id, _vector_to_blob(embedding), quality, utc_now()),
                )
                conn.execute(
                    """INSERT INTO body_samples(event_id, camera_id, person_id, embedding, quality, source, verified, created_at, updated_at)
                    VALUES (?, ?, NULL, ?, ?, 'false_positive', 0, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        person_id = NULL, embedding = excluded.embedding, quality = excluded.quality,
                        source = 'false_positive', verified = 0, updated_at = excluded.updated_at""",
                    (event_id, camera_id, _vector_to_blob(embedding), quality, utc_now(), utc_now()),
                )
            conn.execute(
                "UPDATE events SET probable_person_id = NULL, body_confidence = NULL, body_identity_source = NULL WHERE id = ?",
                (event_id,),
            )
            conn.commit()
        self.notify_change()

    def undo_false_positive(self, event_id: int) -> None:
        self._ensure_aux_schema()
        with connection() as conn:
            sample = conn.execute("SELECT source FROM body_samples WHERE event_id = ?", (event_id,)).fetchone()
            was_auto = bool(sample and sample["source"] == "auto_false_positive")
            conn.execute("DELETE FROM body_negative_samples WHERE event_id = ?", (event_id,))
            if was_auto:
                conn.execute(
                    "INSERT OR REPLACE INTO body_negative_exemptions(event_id, created_at) VALUES (?, ?)",
                    (event_id, utc_now()),
                )
            conn.execute(
                """UPDATE body_samples SET person_id = NULL, verified = 0, source = 'unlabeled', updated_at = ?
                WHERE event_id = ?""",
                (utc_now(), event_id),
            )
            conn.execute(
                "UPDATE events SET probable_person_id = NULL, body_confidence = NULL, body_identity_source = NULL WHERE id = ?",
                (event_id,),
            )
            conn.commit()
        self.notify_change()


manager = BodyIdentityManager()

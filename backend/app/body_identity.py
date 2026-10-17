from __future__ import annotations

import json
import math
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import (
    BODY_REID_FACE_BONUS,
    BODY_REID_MARGIN,
    BODY_REID_MODEL_PATH,
    BODY_REID_POLL_SECONDS,
    BODY_REID_THRESHOLD,
    EVENTS_DIR,
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


def _source_bonus(source: str | None) -> float:
    # Body is never an absolute identity signal. A body sample that was observed
    # in the same event as a confirmed face is simply a stronger ReID reference.
    return BODY_REID_FACE_BONUS if (source or "").startswith("face_verified") else 0.0


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

    @property
    def available(self) -> bool:
        return RUNTIME_AVAILABLE and BODY_REID_MODEL_PATH.is_file()

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
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

    def _run(self) -> None:  # pragma: no cover - background integration
        self.status = "starting"
        try:
            self._ensure_model()
            self.status = "running"
            self.error = None
        except Exception as exc:
            self.status = "unavailable"
            self.error = str(exc)
            return

        while not self.stop_event.is_set():
            try:
                self._sync_verified_labels()
                processed = self.process_pending_once(6)
                self._refresh_probables(80)
                self.status = "running"
                self.error = None
                delay = 0.15 if processed else max(0.35, BODY_REID_POLL_SECONDS)
            except sqlite3.OperationalError:
                # Startup can briefly race the DB migration on old installs.
                delay = 0.8
            except Exception as exc:
                self.status = "error"
                self.error = str(exc)
                delay = 2.0
            self.wake_event.wait(delay)
            self.wake_event.clear()

    def state(self) -> dict[str, Any]:
        try:
            with connection() as conn:
                samples = int(conn.execute("SELECT COUNT(*) FROM body_samples").fetchone()[0])
                verified = int(conn.execute("SELECT COUNT(*) FROM body_samples WHERE verified = 1 AND person_id IS NOT NULL").fetchone()[0])
                probable = int(conn.execute("SELECT COUNT(*) FROM events WHERE person_id IS NULL AND probable_person_id IS NOT NULL").fetchone()[0])
                negatives = int(conn.execute("SELECT COUNT(*) FROM body_negative_samples").fetchone()[0])
        except Exception:
            samples = verified = probable = negatives = 0
        return {
            "status": self.status,
            "error": self.error,
            "available": self.available,
            "samples": samples,
            "verified_samples": verified,
            "probable_events": probable,
            "hard_negatives": negatives,
            "threshold": BODY_REID_THRESHOLD,
            "margin": BODY_REID_MARGIN,
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
        output = self._session.run(None, {self._input_name: tensor})[0]
        return _normalize(output)

    def _event_embedding(self, event: dict[str, Any]) -> tuple[Any, float] | None:
        loaded = self._load_event_crop(event)
        if loaded is None:
            return None
        crop, quality = loaded
        return self._embed_crop(crop), quality

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
            person_id = event.get("person_id")
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
            self._score_event(int(event["id"]), embedding=embedding, quality=quality)

    def _gallery(self) -> list[dict[str, Any]]:
        with connection() as conn:
            rows = conn.execute(
                """SELECT person_id, embedding, quality, source
                FROM body_samples
                WHERE verified = 1 AND person_id IS NOT NULL
                  AND source <> 'false_positive' AND quality >= 0.38"""
            ).fetchall()
        return [dict(row) for row in rows]

    def _score_event(self, event_id: int, *, embedding: Any | None = None, quality: float | None = None) -> None:
        with connection() as conn:
            event = conn.execute(
                "SELECT id, person_id, identity_state FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if event is None or event["person_id"] is not None or event["identity_state"] == "false_positive":
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

    def _refresh_probables(self, limit: int = 80) -> None:
        with connection() as conn:
            rows = conn.execute(
                """SELECT e.id FROM events e JOIN body_samples bs ON bs.event_id = e.id
                WHERE e.person_id IS NULL AND COALESCE(e.identity_state, '') <> 'false_positive'
                ORDER BY e.created_at DESC LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()
        for row in rows:
            self._score_event(int(row["id"]))

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
                        "UPDATE events SET probable_person_id = NULL, body_confidence = NULL, body_identity_source = NULL WHERE id = ?",
                        (row["event_id"],),
                    )
                    changed = True
            if changed:
                conn.commit()

    def confirm_event_identity(self, event_id: int, person_id: int) -> None:
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
            conn.execute(
                "UPDATE events SET probable_person_id = NULL, body_confidence = NULL, body_identity_source = NULL WHERE id = ?",
                (event_id,),
            )
            conn.commit()
        self.notify_change()

    def record_false_positive(self, event_id: int) -> None:
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
            embedded = self._event_embedding(dict(event))
            if embedded is not None:
                embedding, quality = embedded
        with connection() as conn:
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
        with connection() as conn:
            conn.execute("DELETE FROM body_negative_samples WHERE event_id = ?", (event_id,))
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

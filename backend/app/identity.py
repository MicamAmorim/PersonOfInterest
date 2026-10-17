from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    EVENTS_DIR,
    FACES_DIR,
    FACE_DETECTOR_MODEL_PATH,
    FACE_RECOGNIZER_MODEL_PATH,
    IDENTITY_BATCH_SIZE,
    IDENTITY_CLUSTER_THRESHOLD,
    IDENTITY_FACE_SCORE_THRESHOLD,
    IDENTITY_KNOWN_THRESHOLD,
    IDENTITY_POLL_SECONDS,
)
from .db import connection, utc_now

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    CV_AVAILABLE = True
    CV_ERROR: str | None = None
except Exception as exc:  # pragma: no cover
    cv2 = None  # type: ignore
    np = None  # type: ignore
    CV_AVAILABLE = False
    CV_ERROR = str(exc)


def _blob_to_vector(blob: bytes | memoryview | None) -> Any | None:
    if not blob or np is None:
        return None
    vector = np.frombuffer(bytes(blob), dtype=np.float32).astype(np.float32, copy=True)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-9:
        return None
    return vector / norm


def _vector_to_blob(vector: Any) -> bytes:
    return np.asarray(vector, dtype=np.float32).reshape(-1).tobytes()


def _cosine(a: Any, b: Any) -> float:
    return float(np.dot(a, b))


def _normalize(vector: Any) -> Any:
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    return vector / max(norm, 1e-9)


def _event_snapshot_path(relative: str | None) -> Path | None:
    if not relative:
        return None
    path = (EVENTS_DIR / relative).resolve()
    root = EVENTS_DIR.resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def _face_crop_path(relative: str | None) -> Path | None:
    if not relative:
        return None
    path = (FACES_DIR / relative).resolve()
    root = FACES_DIR.resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


class IdentityManager:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()
        self.status = "stopped"
        self.error: str | None = None
        self._detector: Any | None = None
        self._recognizer: Any | None = None

    @property
    def available(self) -> bool:
        return CV_AVAILABLE and FACE_DETECTOR_MODEL_PATH.is_file() and FACE_RECOGNIZER_MODEL_PATH.is_file()

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, name="poi-identity", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=2.5)

    def _ensure_models(self) -> None:
        if not CV_AVAILABLE:
            raise RuntimeError(CV_ERROR or "OpenCV indisponível")
        if not FACE_DETECTOR_MODEL_PATH.is_file():
            raise RuntimeError(f"YuNet não encontrado: {FACE_DETECTOR_MODEL_PATH}")
        if not FACE_RECOGNIZER_MODEL_PATH.is_file():
            raise RuntimeError(f"SFace não encontrado: {FACE_RECOGNIZER_MODEL_PATH}")
        if self._detector is None:
            create = getattr(cv2, "FaceDetectorYN_create", None)
            if create:
                self._detector = create(
                    str(FACE_DETECTOR_MODEL_PATH), "", (320, 320),
                    IDENTITY_FACE_SCORE_THRESHOLD, 0.30, 5000,
                )
            else:
                self._detector = cv2.FaceDetectorYN.create(
                    str(FACE_DETECTOR_MODEL_PATH), "", (320, 320),
                    IDENTITY_FACE_SCORE_THRESHOLD, 0.30, 5000,
                )
        if self._recognizer is None:
            create = getattr(cv2, "FaceRecognizerSF_create", None)
            if create:
                self._recognizer = create(str(FACE_RECOGNIZER_MODEL_PATH), "")
            else:
                self._recognizer = cv2.FaceRecognizerSF.create(str(FACE_RECOGNIZER_MODEL_PATH), "")

    def _run(self) -> None:  # pragma: no cover - background integration
        self.status = "starting"
        try:
            self._ensure_models()
            self.status = "running"
            self.error = None
        except Exception as exc:
            self.status = "unavailable"
            self.error = str(exc)
            return

        while not self.stop_event.is_set():
            try:
                processed = self.process_pending_once(IDENTITY_BATCH_SIZE)
                self.status = "running"
                self.error = None
                self.stop_event.wait(0.15 if processed else max(0.3, IDENTITY_POLL_SECONDS))
            except Exception as exc:
                self.status = "error"
                self.error = str(exc)
                self.stop_event.wait(2.0)

    def state(self) -> dict[str, Any]:
        with connection() as conn:
            counts = {
                row["identity_state"]: int(row["n"])
                for row in conn.execute(
                    "SELECT identity_state, COUNT(*) n FROM events GROUP BY identity_state"
                ).fetchall()
            }
            open_clusters = int(conn.execute(
                "SELECT COUNT(*) FROM unknown_clusters WHERE status = 'open'"
            ).fetchone()[0])
            samples = int(conn.execute("SELECT COUNT(*) FROM face_samples").fetchone()[0])
        return {
            "status": self.status,
            "error": self.error,
            "available": self.available,
            "states": counts,
            "open_clusters": open_clusters,
            "face_samples": samples,
            "known_threshold": IDENTITY_KNOWN_THRESHOLD,
            "cluster_threshold": IDENTITY_CLUSTER_THRESHOLD,
        }

    def process_pending_once(self, limit: int = IDENTITY_BATCH_SIZE) -> int:
        self._ensure_models()
        with connection() as conn:
            rows = conn.execute(
                """SELECT e.id, e.camera_id, e.snapshot_path, e.bbox_json, e.created_at
                FROM events e
                LEFT JOIN face_samples fs ON fs.event_id = e.id
                WHERE fs.id IS NULL AND e.snapshot_path IS NOT NULL
                  AND COALESCE(e.identity_state, 'pending') = 'pending'
                ORDER BY e.created_at ASC LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()
        for row in rows:
            if self.stop_event.is_set():
                break
            self._index_event(dict(row))
        return len(rows)

    def _index_event(self, event: dict[str, Any]) -> None:
        path = _event_snapshot_path(event.get("snapshot_path"))
        if path is None:
            self._set_event_state(int(event["id"]), "missing_snapshot", None, None, None)
            return
        frame = cv2.imread(str(path))
        if frame is None:
            self._set_event_state(int(event["id"]), "missing_snapshot", None, None, None)
            return

        face = self._best_face(frame, event.get("bbox_json"))
        if face is None:
            self._set_event_state(int(event["id"]), "no_face", None, None, None)
            return

        aligned = self._recognizer.alignCrop(frame, face)
        feature = self._recognizer.feature(aligned)
        embedding = _normalize(feature)
        score = float(face[-1])
        fw, fh = max(1.0, float(face[2])), max(1.0, float(face[3]))
        quality = float(score * min(1.0, math.sqrt(fw * fh) / 110.0))
        crop_relative = self._save_crop(aligned, event)

        person_id, known_score = self._match_known(embedding)
        if person_id is not None:
            self._persist_sample(
                event, embedding, crop_relative, quality,
                person_id=person_id, cluster_id=None,
                identity_state="known", identity_confidence=known_score,
            )
            return

        cluster_id, cluster_score = self._match_or_create_cluster(embedding, crop_relative, quality, event["created_at"])
        self._persist_sample(
            event, embedding, crop_relative, quality,
            person_id=None, cluster_id=cluster_id,
            identity_state="unknown", identity_confidence=cluster_score,
        )

    def _best_face(self, frame: Any, bbox_json: str | None) -> Any | None:
        height, width = frame.shape[:2]
        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(frame)
        if faces is None or len(faces) == 0:
            return None
        bbox: dict[str, Any] | None = None
        if bbox_json:
            try:
                bbox = json.loads(bbox_json)
            except Exception:
                bbox = None
        candidates: list[Any] = []
        if bbox:
            x, y = float(bbox.get("x", 0)), float(bbox.get("y", 0))
            w, h = float(bbox.get("w", 0)), float(bbox.get("h", 0))
            for face in faces:
                cx = float(face[0] + face[2] / 2)
                cy = float(face[1] + face[3] / 2)
                if x <= cx <= x + w and y <= cy <= y + h:
                    candidates.append(face)
        if not candidates:
            candidates = list(faces)
        return max(candidates, key=lambda f: float(f[-1]) * max(1.0, float(f[2] * f[3])))

    def _save_crop(self, aligned: Any, event: dict[str, Any]) -> str | None:
        created = str(event.get("created_at") or utc_now())[:10]
        folder = FACES_DIR / created / str(event["camera_id"])
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"event_{event['id']}.jpg"
        if not cv2.imwrite(str(path), aligned, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
            return None
        return str(path.relative_to(FACES_DIR)).replace("\\", "/")

    def _match_known(self, embedding: Any) -> tuple[int | None, float | None]:
        with connection() as conn:
            rows = conn.execute(
                "SELECT person_id, embedding FROM face_samples WHERE person_id IS NOT NULL"
            ).fetchall()
        best_person: int | None = None
        best_score = -1.0
        for row in rows:
            candidate = _blob_to_vector(row["embedding"])
            if candidate is None:
                continue
            score = _cosine(embedding, candidate)
            if score > best_score:
                best_score = score
                best_person = int(row["person_id"])
        if best_person is not None and best_score >= IDENTITY_KNOWN_THRESHOLD:
            return best_person, best_score
        return None, None

    def _match_or_create_cluster(
        self,
        embedding: Any,
        crop_relative: str | None,
        quality: float,
        seen_at: str,
    ) -> tuple[int, float | None]:
        with connection() as conn:
            rows = conn.execute(
                "SELECT * FROM unknown_clusters WHERE status = 'open'"
            ).fetchall()
        best_id: int | None = None
        best_score = -1.0
        best_row: Any | None = None
        for row in rows:
            centroid = _blob_to_vector(row["centroid"])
            if centroid is None:
                continue
            score = _cosine(embedding, centroid)
            if score > best_score:
                best_score = score
                best_id = int(row["id"])
                best_row = row
        now = utc_now()
        with connection() as conn:
            if best_id is None or best_score < IDENTITY_CLUSTER_THRESHOLD:
                cursor = conn.execute(
                    """INSERT INTO unknown_clusters(
                        centroid, sample_count, representative_crop_path, representative_quality,
                        first_seen, last_seen, status, created_at, updated_at
                    ) VALUES (?, 1, ?, ?, ?, ?, 'open', ?, ?)""",
                    (_vector_to_blob(embedding), crop_relative, quality, seen_at, seen_at, now, now),
                )
                conn.commit()
                return int(cursor.lastrowid), None

            count = max(1, int(best_row["sample_count"]))
            centroid = _blob_to_vector(best_row["centroid"])
            new_centroid = _normalize((centroid * count + embedding) / (count + 1))
            representative = best_row["representative_crop_path"]
            representative_quality = float(best_row["representative_quality"] or 0.0)
            if crop_relative and quality > representative_quality:
                representative = crop_relative
                representative_quality = quality
            conn.execute(
                """UPDATE unknown_clusters
                SET centroid = ?, sample_count = ?, representative_crop_path = ?, representative_quality = ?,
                    last_seen = ?, updated_at = ? WHERE id = ?""",
                (
                    _vector_to_blob(new_centroid), count + 1, representative, representative_quality,
                    seen_at, now, best_id,
                ),
            )
            conn.commit()
        return best_id, best_score

    def _persist_sample(
        self,
        event: dict[str, Any],
        embedding: Any,
        crop_relative: str | None,
        quality: float,
        *,
        person_id: int | None,
        cluster_id: int | None,
        identity_state: str,
        identity_confidence: float | None,
    ) -> None:
        now = utc_now()
        with connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO face_samples(
                    event_id, camera_id, person_id, cluster_id, embedding, crop_path, quality, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["id"], event["camera_id"], person_id, cluster_id,
                    _vector_to_blob(embedding), crop_relative, quality, now,
                ),
            )
            conn.execute(
                """UPDATE events SET person_id = ?, unknown_cluster_id = ?, identity_state = ?,
                    identity_confidence = ?, has_face = 1, face_count = MAX(face_count, 1)
                WHERE id = ?""",
                (person_id, cluster_id, identity_state, identity_confidence, event["id"]),
            )
            conn.commit()

    def _set_event_state(
        self,
        event_id: int,
        state: str,
        person_id: int | None,
        cluster_id: int | None,
        confidence: float | None,
    ) -> None:
        with connection() as conn:
            conn.execute(
                """UPDATE events SET identity_state = ?, person_id = ?, unknown_cluster_id = ?, identity_confidence = ?
                WHERE id = ?""",
                (state, person_id, cluster_id, confidence, event_id),
            )
            conn.commit()

    def list_clusters(self) -> list[dict[str, Any]]:
        with connection() as conn:
            rows = conn.execute(
                """SELECT uc.*, COUNT(DISTINCT e.camera_id) AS camera_count,
                    GROUP_CONCAT(DISTINCT c.name) AS cameras
                FROM unknown_clusters uc
                LEFT JOIN events e ON e.unknown_cluster_id = uc.id
                LEFT JOIN cameras c ON c.id = e.camera_id
                WHERE uc.status = 'open'
                GROUP BY uc.id ORDER BY uc.last_seen DESC"""
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "sample_count": int(row["sample_count"]),
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "camera_count": int(row["camera_count"] or 0),
                "cameras": row["cameras"] or "",
                "face_url": f"/api/identity/clusters/{row['id']}/face" if row["representative_crop_path"] else None,
            }
            for row in rows
        ]

    def cluster_face_path(self, cluster_id: int) -> Path | None:
        with connection() as conn:
            row = conn.execute(
                "SELECT representative_crop_path FROM unknown_clusters WHERE id = ?",
                (cluster_id,),
            ).fetchone()
        return _face_crop_path(row["representative_crop_path"]) if row else None

    def _get_or_create_person(self, name: str) -> int:
        clean = name.strip()
        if not clean:
            raise ValueError("Nome da pessoa não pode ficar vazio")
        with connection() as conn:
            row = conn.execute(
                "SELECT id FROM persons WHERE name = ? COLLATE NOCASE ORDER BY id LIMIT 1",
                (clean,),
            ).fetchone()
            if row:
                return int(row["id"])
            now = utc_now()
            cursor = conn.execute(
                "INSERT INTO persons(name, created_at, updated_at) VALUES (?, ?, ?)",
                (clean, now, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def assign_cluster(self, cluster_id: int, *, person_id: int | None = None, name: str | None = None) -> dict[str, Any]:
        if person_id is None:
            if not name:
                raise ValueError("Informe uma pessoa existente ou um novo nome")
            person_id = self._get_or_create_person(name)
        with connection() as conn:
            person = conn.execute("SELECT id, name FROM persons WHERE id = ?", (person_id,)).fetchone()
            cluster = conn.execute("SELECT id FROM unknown_clusters WHERE id = ?", (cluster_id,)).fetchone()
            if person is None:
                raise LookupError("Pessoa não encontrada")
            if cluster is None:
                raise LookupError("Grupo desconhecido não encontrado")
            now = utc_now()
            conn.execute(
                "UPDATE face_samples SET person_id = ?, cluster_id = NULL WHERE cluster_id = ?",
                (person_id, cluster_id),
            )
            conn.execute(
                """UPDATE events SET person_id = ?, unknown_cluster_id = NULL,
                    identity_state = 'known', identity_confidence = 1.0
                WHERE unknown_cluster_id = ?""",
                (person_id, cluster_id),
            )
            conn.execute(
                """UPDATE unknown_clusters SET status = 'assigned', assigned_person_id = ?, updated_at = ?
                WHERE id = ?""",
                (person_id, now, cluster_id),
            )
            affected = int(conn.execute("SELECT changes()").fetchone()[0])
            conn.commit()
        return {"ok": True, "cluster_id": cluster_id, "person_id": person_id, "person_name": person["name"], "affected": affected}

    def assign_event(self, event_id: int, *, person_id: int | None = None, name: str | None = None) -> dict[str, Any]:
        with connection() as conn:
            event = conn.execute("SELECT id, unknown_cluster_id FROM events WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            raise LookupError("Evento não encontrado")
        if event["unknown_cluster_id"] is not None:
            return self.assign_cluster(int(event["unknown_cluster_id"]), person_id=person_id, name=name)
        if person_id is None:
            if not name:
                raise ValueError("Informe uma pessoa existente ou um novo nome")
            person_id = self._get_or_create_person(name)
        with connection() as conn:
            person = conn.execute("SELECT id, name FROM persons WHERE id = ?", (person_id,)).fetchone()
            if person is None:
                raise LookupError("Pessoa não encontrada")
            conn.execute(
                "UPDATE events SET person_id = ?, identity_state = 'known', identity_confidence = 1.0 WHERE id = ?",
                (person_id, event_id),
            )
            conn.execute("UPDATE face_samples SET person_id = ?, cluster_id = NULL WHERE event_id = ?", (person_id, event_id))
            conn.commit()
        return {"ok": True, "event_id": event_id, "person_id": person_id, "person_name": person["name"], "affected": 1}

    def reindex(self, *, include_no_face: bool = False) -> dict[str, int]:
        with connection() as conn:
            if include_no_face:
                event_rows = conn.execute("SELECT id FROM events WHERE snapshot_path IS NOT NULL").fetchall()
            else:
                event_rows = conn.execute(
                    """SELECT e.id FROM events e LEFT JOIN face_samples fs ON fs.event_id = e.id
                    WHERE e.snapshot_path IS NOT NULL AND fs.id IS NULL"""
                ).fetchall()
            ids = [int(row["id"]) for row in event_rows]
            if ids:
                marks = ",".join("?" for _ in ids)
                conn.execute(f"UPDATE events SET identity_state = 'pending' WHERE id IN ({marks})", ids)
                if include_no_face:
                    conn.execute(f"DELETE FROM face_samples WHERE event_id IN ({marks})", ids)
            conn.commit()
        return {"queued": len(ids)}


manager = IdentityManager()

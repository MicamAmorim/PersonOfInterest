from __future__ import annotations

import math
import threading
import time
from typing import Any

from . import body_identity as bi
from . import identity as fi
from . import vision
from .db import connection, utc_now
from .tracking_v5_patch import PersistentTrack, ensure_schema


_REFINE_COOLDOWN_SECONDS = 1.35
_REFINE_MIN_TRACK_FACE_QUALITY = 0.48
_REFINE_QUALITY_DELTA = 0.035


def _fresh_face_models() -> tuple[Any, Any]:
    create_detector = getattr(fi.cv2, "FaceDetectorYN_create", None)
    detector = (
        create_detector(
            str(fi.FACE_DETECTOR_MODEL_PATH), "", (320, 320),
            fi.IDENTITY_FACE_SCORE_THRESHOLD, 0.30, 5000,
        )
        if create_detector
        else fi.cv2.FaceDetectorYN.create(
            str(fi.FACE_DETECTOR_MODEL_PATH), "", (320, 320),
            fi.IDENTITY_FACE_SCORE_THRESHOLD, 0.30, 5000,
        )
    )
    create_recognizer = getattr(fi.cv2, "FaceRecognizerSF_create", None)
    recognizer = (
        create_recognizer(str(fi.FACE_RECOGNIZER_MODEL_PATH), "")
        if create_recognizer
        else fi.cv2.FaceRecognizerSF.create(str(fi.FACE_RECOGNIZER_MODEL_PATH), "")
    )
    return detector, recognizer


def _models_for_worker(worker: Any) -> tuple[Any, Any] | None:
    if not fi.CV_AVAILABLE or not fi.FACE_DETECTOR_MODEL_PATH.is_file() or not fi.FACE_RECOGNIZER_MODEL_PATH.is_file():
        return None
    if not hasattr(worker, "_v5_refine_face_models"):
        worker._v5_refine_face_models = _fresh_face_models()
    return worker._v5_refine_face_models


def _best_face_for_track(frame: Any, track: PersistentTrack, detector: Any) -> Any | None:
    height, width = frame.shape[:2]
    detector.setInputSize((width, height))
    _, faces = detector.detect(frame)
    if faces is None or len(faces) == 0:
        return None
    x, y, w, h = track.bbox
    candidates = []
    for face in faces:
        cx = float(face[0] + face[2] / 2)
        cy = float(face[1] + face[3] / 2)
        if x <= cx <= x + w and max(0, y - int(h * 0.18)) <= cy <= y + h:
            candidates.append(face)
    if not candidates:
        return None
    return max(candidates, key=lambda value: float(value[-1]) * max(1.0, float(value[2] * value[3])))


def _rebuild_unknown_cluster(cluster_id: int) -> None:
    """Recompute a cluster exactly after one event leaves it for a known person."""
    with connection() as conn:
        rows = conn.execute(
            """SELECT fs.embedding, fs.crop_path, fs.quality, e.created_at
            FROM face_samples fs
            JOIN events e ON e.id = fs.event_id
            WHERE fs.cluster_id = ?
            ORDER BY e.created_at ASC""",
            (cluster_id,),
        ).fetchall()
        if not rows:
            conn.execute("DELETE FROM unknown_clusters WHERE id = ?", (cluster_id,))
            conn.commit()
            return
        vectors = [fi._blob_to_vector(row["embedding"]) for row in rows]
        vectors = [vector for vector in vectors if vector is not None]
        if not vectors:
            conn.execute("DELETE FROM unknown_clusters WHERE id = ?", (cluster_id,))
            conn.commit()
            return
        centroid = fi._normalize(sum(vectors) / max(1, len(vectors)))
        best = max(rows, key=lambda row: float(row["quality"] or 0.0))
        first_seen = str(rows[0]["created_at"])
        last_seen = str(rows[-1]["created_at"])
        conn.execute(
            """UPDATE unknown_clusters
            SET centroid = ?, sample_count = ?, representative_crop_path = ?,
                representative_quality = ?, first_seen = ?, last_seen = ?, updated_at = ?
            WHERE id = ?""",
            (
                fi._vector_to_blob(centroid), len(rows), best["crop_path"],
                float(best["quality"] or 0.0), first_seen, last_seen, utc_now(), cluster_id,
            ),
        )
        conn.commit()


def _promote_unknown_event(worker: Any, track: PersistentTrack, frame: Any, detector: Any, recognizer: Any) -> bool:
    if track.event_id is None:
        return False
    with connection() as conn:
        event_row = conn.execute(
            "SELECT * FROM events WHERE id = ? AND identity_state = 'unknown' AND person_id IS NULL",
            (track.event_id,),
        ).fetchone()
        sample_row = conn.execute(
            "SELECT cluster_id, quality FROM face_samples WHERE event_id = ?",
            (track.event_id,),
        ).fetchone()
    if event_row is None or sample_row is None:
        return False

    face = _best_face_for_track(frame, track, detector)
    if face is None:
        return False
    aligned = recognizer.alignCrop(frame, face)
    embedding = fi._normalize(recognizer.feature(aligned))
    score = float(face[-1])
    fw, fh = max(1.0, float(face[2])), max(1.0, float(face[3]))
    quality = max(0.0, min(1.0, score * min(1.0, math.sqrt(fw * fh) / 110.0)))
    previous_quality = float(sample_row["quality"] or 0.0)
    if quality < previous_quality + 0.02:
        return False

    person_id, known_score = fi.manager._match_known(embedding)
    if person_id is None:
        # A better unknown face is intentionally not inserted into the cluster a
        # second time. We retry only when an even better face appears later.
        return False

    event = dict(event_row)
    crop_relative = fi.manager._save_crop(aligned, event)
    old_cluster = sample_row["cluster_id"] or event_row["unknown_cluster_id"]
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """UPDATE face_samples SET person_id = ?, cluster_id = NULL, embedding = ?,
                crop_path = ?, quality = ? WHERE event_id = ?""",
            (person_id, fi._vector_to_blob(embedding), crop_relative, quality, track.event_id),
        )
        conn.execute(
            """UPDATE events SET person_id = ?, probable_person_id = NULL,
                body_confidence = NULL, body_identity_source = NULL,
                unknown_cluster_id = NULL, identity_state = 'known',
                identity_confidence = ?, identity_origin = 'face', assistant_eligible = 1,
                has_face = 1, face_count = MAX(face_count, 1), best_face_quality = MAX(best_face_quality, ?)
            WHERE id = ?""",
            (person_id, known_score, quality, track.event_id),
        )
        conn.commit()
    if old_cluster is not None:
        _rebuild_unknown_cluster(int(old_cluster))
    bi.manager.notify_change()
    return True


def install() -> None:
    cls = vision.CameraVisionWorker
    if getattr(cls, "_poi_v5_face_refinement", False):
        return
    original_process = cls._process

    def process_with_refinement(self: Any, frame: Any, detector: Any, face_cascade: Any) -> None:
        original_process(self, frame, detector, face_cascade)
        try:
            ensure_schema()
            models = _models_for_worker(self)
            if models is None:
                return
            face_detector, recognizer = models
            if not hasattr(self, "_v5_refine_state"):
                self._v5_refine_state = {}
            now = time.monotonic()
            live_frame = None
            if hasattr(self, "live_frame_lock"):
                with self.live_frame_lock:
                    live_frame = None if self.live_frame is None else self.live_frame.copy()
            if live_frame is None:
                live_frame = frame
            for track in self.tracker.tracks.values():
                if not isinstance(track, PersistentTrack) or track.event_id is None or track.missed != 0 or not track.face_seen_now:
                    continue
                if float(track.best_face_quality) < _REFINE_MIN_TRACK_FACE_QUALITY:
                    continue
                last = self._v5_refine_state.get(int(track.event_id), {"at": 0.0, "quality": 0.0})
                if now - float(last.get("at", 0.0)) < _REFINE_COOLDOWN_SECONDS:
                    continue
                if float(track.best_face_quality) < float(last.get("quality", 0.0)) + _REFINE_QUALITY_DELTA:
                    continue
                self._v5_refine_state[int(track.event_id)] = {"at": now, "quality": float(track.best_face_quality)}
                _promote_unknown_event(self, track, live_frame, face_detector, recognizer)
        except Exception as exc:
            # Refinement is opportunistic. It must never interrupt detector/PTZ.
            self.error = f"Face refinement: {exc}"

    cls._process = process_with_refinement
    cls._poi_v5_face_refinement = True

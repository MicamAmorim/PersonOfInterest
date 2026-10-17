from __future__ import annotations

import json
import math
import threading
from typing import Any

from . import body_identity as bi
from . import identity as fi
from .assistant import manager as assistant_manager
from .db import connection, utc_now


def _extract_face_reference(event: dict[str, Any], person_id: int) -> bool:
    """Create a verified face sample for a manually confirmed event when possible.

    A separate YuNet/SFace instance is used so manual review cannot race the
    background identity worker's mutable detector input size. When the event has
    a person bounding box, only faces whose center lies inside that box are
    eligible; this prevents learning another person's face from the same frame.
    """
    path = fi._event_snapshot_path(event.get("snapshot_path"))
    if path is None or fi.cv2 is None:
        return False
    frame = fi.cv2.imread(str(path))
    if frame is None:
        return False

    try:
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
        height, width = frame.shape[:2]
        detector.setInputSize((width, height))
        _, faces = detector.detect(frame)
        if faces is None or len(faces) == 0:
            return False

        bbox = None
        try:
            parsed = json.loads(event.get("bbox_json") or "{}")
            if float(parsed.get("w", 0)) > 0 and float(parsed.get("h", 0)) > 0:
                bbox = parsed
        except Exception:
            bbox = None

        candidates = []
        if bbox:
            x, y = float(bbox.get("x", 0)), float(bbox.get("y", 0))
            w, h = float(bbox.get("w", 0)), float(bbox.get("h", 0))
            for face in faces:
                cx = float(face[0] + face[2] / 2)
                cy = float(face[1] + face[3] / 2)
                if x <= cx <= x + w and y <= cy <= y + h:
                    candidates.append(face)
            if not candidates:
                return False
        else:
            candidates = list(faces)

        face = max(candidates, key=lambda f: float(f[-1]) * max(1.0, float(f[2] * f[3])))
        aligned = recognizer.alignCrop(frame, face)
        embedding = fi._normalize(recognizer.feature(aligned))
        score = float(face[-1])
        fw, fh = max(1.0, float(face[2])), max(1.0, float(face[3]))
        quality = float(score * min(1.0, math.sqrt(fw * fh) / 110.0))
        crop_relative = fi.manager._save_crop(aligned, event)
        now = utc_now()
        with connection() as conn:
            conn.execute(
                """INSERT INTO face_samples(
                    event_id, camera_id, person_id, cluster_id, embedding, crop_path, quality, created_at
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    person_id = excluded.person_id,
                    cluster_id = NULL,
                    embedding = excluded.embedding,
                    crop_path = excluded.crop_path,
                    quality = excluded.quality""",
                (
                    event["id"], event["camera_id"], person_id,
                    fi._vector_to_blob(embedding), crop_relative, quality, now,
                ),
            )
            conn.execute(
                """UPDATE events SET person_id = ?, unknown_cluster_id = NULL,
                    identity_state = 'known', identity_confidence = 1.0,
                    has_face = 1, face_count = MAX(face_count, 1)
                WHERE id = ?""",
                (person_id, event["id"]),
            )
            conn.commit()
        return True
    except Exception:
        return False


def _assistant_payload(event_id: int) -> dict[str, Any] | None:
    assistant_manager.ensure_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT e.*, c.name AS camera_name, c.stream_name, c.rtsp_url, c.sync_status,
                s.interval_minutes, s.voice_gender, s.timezone, s.updated_at AS assistant_updated_at,
                p.name AS person_name, pp.name AS probable_person_name,
                fs.quality AS face_quality
            FROM events e
            JOIN cameras c ON c.id = e.camera_id
            JOIN camera_assistant_settings s ON s.camera_id = e.camera_id AND s.enabled = 1
            LEFT JOIN persons p ON p.id = e.person_id
            LEFT JOIN persons pp ON pp.id = e.probable_person_id
            LEFT JOIN face_samples fs ON fs.event_id = e.id
            WHERE e.id = ?""",
            (event_id,),
        ).fetchone()
    return dict(row) if row else None


def _reconsider_assistant(event_id: int) -> None:
    """Re-evaluate one manually confirmed event even if it was already consumed."""
    try:
        payload = _assistant_payload(event_id)
        if payload is None:
            return
        assistant_manager._handle_event(payload)
    except Exception as exc:
        assistant_manager.error = f"Reavaliação após cadastro manual: {exc}"


def _reinforce_manual_event(self: Any, event_id: int, person_id: int) -> None:
    original = getattr(type(self), "_poi_original_confirm_event_identity")
    original(self, event_id, person_id)

    with connection() as conn:
        event_row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        face_row = conn.execute(
            "SELECT id FROM face_samples WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    if event_row is None:
        return
    event = dict(event_row)

    # Existing face embeddings become verified references after a manual
    # correction. If indexing has not produced one yet, try to extract it now.
    face_reference = face_row is not None
    if face_reference:
        with connection() as conn:
            conn.execute(
                "UPDATE face_samples SET person_id = ?, cluster_id = NULL WHERE event_id = ?",
                (person_id, event_id),
            )
            conn.commit()
    else:
        face_reference = _extract_face_reference(event, person_id)

    # The same manual confirmation also reinforces appearance ReID. This never
    # promotes future body matches to absolute identity: it only creates a
    # verified reference used by probable_person_id scoring.
    source = "face_verified_manual" if face_reference else "manual_verified"
    body_reference = False
    with connection() as conn:
        body_row = conn.execute(
            "SELECT id FROM body_samples WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    if body_row is not None:
        with connection() as conn:
            conn.execute(
                """UPDATE body_samples
                SET person_id = ?, verified = 1, source = ?, updated_at = ?
                WHERE event_id = ?""",
                (person_id, source, utc_now(), event_id),
            )
            conn.execute("DELETE FROM body_negative_samples WHERE event_id = ?", (event_id,))
            conn.commit()
        body_reference = True
    else:
        try:
            embedded = self._event_embedding(event)
            if embedded is not None:
                embedding, quality = embedded
                now = utc_now()
                with connection() as conn:
                    conn.execute(
                        """INSERT INTO body_samples(
                            event_id, camera_id, person_id, embedding, quality, source,
                            verified, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                        ON CONFLICT(event_id) DO UPDATE SET
                            person_id = excluded.person_id,
                            embedding = excluded.embedding,
                            quality = excluded.quality,
                            source = excluded.source,
                            verified = 1,
                            updated_at = excluded.updated_at""",
                        (
                            event_id, event["camera_id"], person_id,
                            bi._vector_to_blob(embedding), quality, source, now, now,
                        ),
                    )
                    conn.execute("DELETE FROM body_negative_samples WHERE event_id = ?", (event_id,))
                    conn.commit()
                body_reference = True
        except Exception as exc:
            self.error = f"Referência corporal manual pendente: {exc}"

    with connection() as conn:
        conn.execute(
            """UPDATE events SET person_id = ?, probable_person_id = NULL,
                body_confidence = NULL, body_identity_source = NULL,
                identity_state = 'known', identity_confidence = 1.0
            WHERE id = ?""",
            (person_id, event_id),
        )
        conn.commit()

    # Re-run assistant logic on this event in a daemon thread. The normal poller
    # may already have consumed it as unknown/no-face; direct reconsideration
    # lets a newly created person receive their first turn greeting immediately.
    try:
        payload = _assistant_payload(event_id)
        if payload is not None:
            thread = threading.Thread(
                target=_reconsider_assistant,
                args=(event_id,),
                name=f"poi-assistant-manual-{event_id}",
                daemon=True,
            )
            thread.start()
    except Exception:
        pass

    self._last_manual_learning = {
        "event_id": event_id,
        "person_id": person_id,
        "face_reference": face_reference,
        "body_reference": body_reference,
        "updated_at": utc_now(),
    }
    self.notify_change()


def install() -> None:
    cls = bi.BodyIdentityManager
    if getattr(cls, "_poi_manual_learning_patch", False):
        return
    cls._poi_original_confirm_event_identity = cls.confirm_event_identity
    cls.confirm_event_identity = _reinforce_manual_event
    cls._poi_manual_learning_patch = True

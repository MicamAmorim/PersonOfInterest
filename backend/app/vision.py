from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import ptz
from .config import (
    EVENTS_DIR,
    VISION_EVENT_COOLDOWN_SECONDS,
    VISION_MAX_WIDTH,
    VISION_MODEL_PATH,
    VISION_NMS_THRESHOLD,
    VISION_PERSON_CONFIDENCE,
    VISION_PROCESS_FPS,
)
from .db import connection, utc_now
from .yolox_detector import YoloXPersonDetector

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    CV_AVAILABLE = True
    CV_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - environment boundary
    cv2 = None  # type: ignore
    np = None  # type: ignore
    CV_AVAILABLE = False
    CV_IMPORT_ERROR = str(exc)


@dataclass(slots=True)
class Track:
    id: int
    bbox: tuple[int, int, int, int]
    confidence: float
    hits: int = 1
    missed: int = 0
    has_face: bool = False
    face_count: int = 0
    event_id: int | None = None
    created_monotonic: float = field(default_factory=time.monotonic)
    last_seen_monotonic: float = field(default_factory=time.monotonic)


def _center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    x, y, w, h = box
    return x + w / 2, y + h / 2


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


class CentroidTracker:
    """Small CPU-friendly tracker based on IoU + normalized centroid distance."""

    def __init__(self) -> None:
        self.next_id = 1
        self.tracks: dict[int, Track] = {}

    def update(
        self,
        detections: list[tuple[tuple[int, int, int, int], float]],
        frame_shape: tuple[int, ...],
    ) -> list[Track]:
        height, width = frame_shape[:2]
        diag = math.hypot(width, height)
        unmatched = set(range(len(detections)))

        for track in list(self.tracks.values()):
            best_idx: int | None = None
            best_score = -1.0
            tcx, tcy = _center(track.bbox)
            for idx in unmatched:
                bbox, _ = detections[idx]
                dcx, dcy = _center(bbox)
                distance = math.hypot(tcx - dcx, tcy - dcy) / max(diag, 1.0)
                overlap = _iou(track.bbox, bbox)
                score = overlap * 1.7 + max(0.0, 0.24 - distance)
                if (overlap >= 0.12 or distance <= 0.12) and score > best_score:
                    best_idx, best_score = idx, score

            if best_idx is None:
                track.missed += 1
                if track.missed > 5:
                    self.tracks.pop(track.id, None)
                continue

            bbox, conf = detections[best_idx]
            unmatched.remove(best_idx)
            track.bbox = bbox
            track.confidence = conf
            track.hits += 1
            track.missed = 0
            track.last_seen_monotonic = time.monotonic()

        for idx in unmatched:
            bbox, conf = detections[idx]
            track = Track(self.next_id, bbox, conf)
            self.tracks[track.id] = track
            self.next_id += 1

        return [t for t in self.tracks.values() if t.missed <= 2]


class CameraVisionWorker(threading.Thread):
    def __init__(
        self,
        manager: "VisionManager",
        camera_id: int,
        source_url: str,
        camera_rtsp_url: str,
        camera_name: str,
    ) -> None:
        super().__init__(name=f"poi-vision-{camera_id}", daemon=True)
        self.manager = manager
        self.camera_id = camera_id
        self.source_url = source_url
        self.camera_rtsp_url = camera_rtsp_url
        self.camera_name = camera_name
        self.stop_event = threading.Event()
        self.tracker = CentroidTracker()
        self.last_event_at = 0.0
        self.last_follow_move = 0.0
        self.status = "starting"
        self.error: str | None = None
        self.frame_size = (0, 0)
        self.tracks_state: list[dict[str, Any]] = []

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:  # pragma: no cover - camera I/O
        if not CV_AVAILABLE:
            self.status = "unavailable"
            self.error = CV_IMPORT_ERROR
            return

        try:
            detector = YoloXPersonDetector(
                VISION_MODEL_PATH,
                confidence=VISION_PERSON_CONFIDENCE,
                nms_threshold=VISION_NMS_THRESHOLD,
            )
        except Exception as exc:
            self.status = "error"
            self.error = f"Falha ao carregar YOLOX ONNX: {exc}"
            return

        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        target_interval = 1.0 / max(0.2, VISION_PROCESS_FPS)

        while not self.stop_event.is_set():
            cap = cv2.VideoCapture(self.source_url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                self.status = "error"
                self.error = "Não foi possível abrir o restream local para visão computacional"
                time.sleep(2.0)
                continue

            self.status, self.error = "running", None
            last_processed = 0.0
            try:
                while not self.stop_event.is_set():
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        self.status = "reconnecting"
                        break
                    now = time.monotonic()
                    if now - last_processed < target_interval:
                        continue
                    last_processed = now
                    self._process(frame, detector, face_cascade)
            finally:
                cap.release()

            if not self.stop_event.is_set():
                time.sleep(1.0)

    def _process(self, frame: Any, detector: YoloXPersonDetector, face_cascade: Any) -> None:
        h0, w0 = frame.shape[:2]
        if w0 > VISION_MAX_WIDTH:
            scale = VISION_MAX_WIDTH / float(w0)
            frame = cv2.resize(frame, (VISION_MAX_WIDTH, int(h0 * scale)))

        height, width = frame.shape[:2]
        self.frame_size = (width, height)

        detections = detector.detect(frame)
        tracks = self.tracker.update(detections, frame.shape)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.12,
            minNeighbors=5,
            minSize=(34, 34),
        )
        face_boxes = [tuple(map(int, f)) for f in faces]

        for track in tracks:
            x, y, w, h = track.bbox
            associated: list[tuple[int, int, int, int]] = []
            for face in face_boxes:
                fx, fy, fw, fh = face
                cx, cy = fx + fw / 2, fy + fh / 2
                if x <= cx <= x + w and y <= cy <= y + h:
                    associated.append(face)

            had_face_before = track.has_face
            if associated:
                track.has_face = True
                track.face_count = max(track.face_count, len(associated))

            if (
                track.hits >= 2
                and track.event_id is None
                and time.monotonic() - self.last_event_at >= VISION_EVENT_COOLDOWN_SECONDS
            ):
                track.event_id = self._save_event(frame, track, associated)
                self.last_event_at = time.monotonic()
            elif track.event_id and associated and not had_face_before:
                self._mark_face(track.event_id, len(associated))

        self.tracks_state = [
            {
                "track_id": t.id,
                "bbox": {
                    "x": t.bbox[0] / width,
                    "y": t.bbox[1] / height,
                    "w": t.bbox[2] / width,
                    "h": t.bbox[3] / height,
                },
                "confidence": round(float(t.confidence), 3),
                "has_face": t.has_face,
                "face_count": t.face_count,
            }
            for t in tracks
        ]
        self._auto_follow(tracks, width, height)

    def _save_event(
        self,
        frame: Any,
        track: Track,
        faces: list[tuple[int, int, int, int]],
    ) -> int | None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        folder = EVENTS_DIR / day / str(self.camera_id)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%H%M%S_%f")
        path = folder / f"track_{track.id}_{stamp}.jpg"

        annotated = frame.copy()
        x, y, w, h = track.bbox
        cv2.rectangle(annotated, (x, y), (x + w, y + h), (255, 255, 255), 2)
        cv2.putText(
            annotated,
            f"Person #{track.id}",
            (x, max(20, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
        )
        for fx, fy, fw, fh in faces:
            cv2.rectangle(annotated, (fx, fy), (fx + fw, fy + fh), (180, 180, 180), 1)

        if not cv2.imwrite(str(path), annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 86]):
            return None

        relative = str(path.relative_to(EVENTS_DIR)).replace("\\", "/")
        with connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events(
                    camera_id, track_id, event_type, has_face, face_count,
                    confidence, snapshot_path, bbox_json, created_at
                )
                VALUES (?, ?, 'person', ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.camera_id,
                    track.id,
                    int(bool(faces)),
                    len(faces),
                    float(track.confidence),
                    relative,
                    json.dumps({"x": x, "y": y, "w": w, "h": h}),
                    utc_now(),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def _mark_face(self, event_id: int, face_count: int) -> None:
        with connection() as conn:
            conn.execute(
                "UPDATE events SET has_face = 1, face_count = MAX(face_count, ?) WHERE id = ?",
                (face_count, event_id),
            )
            conn.commit()

    def _auto_follow(self, tracks: list[Track], width: int, height: int) -> None:
        settings = self.manager.settings_for(self.camera_id)
        if not settings.get("auto_follow_enabled") or not tracks:
            return

        selected = settings.get("selected_track_id")
        target = next((t for t in tracks if t.id == selected), None)
        if target is None:
            target = max(tracks, key=lambda t: t.bbox[2] * t.bbox[3])

        cx, cy = _center(target.bbox)
        dx = cx / width - 0.5
        dy = cy / height - 0.5
        dead = 0.16
        pan = 0.0 if abs(dx) < dead else (1.0 if dx > 0 else -1.0)
        tilt = 0.0 if abs(dy) < dead else (-1.0 if dy > 0 else 1.0)
        now = time.monotonic()

        if (pan or tilt) and now - self.last_follow_move > 0.75:
            speed = min(0.7, 0.30 + max(abs(dx), abs(dy)))
            self.last_follow_move = now
            threading.Thread(
                target=self._ptz_pulse,
                args=(pan, tilt, speed),
                daemon=True,
            ).start()

    def _ptz_pulse(self, pan: float, tilt: float, speed: float) -> None:
        try:
            ptz.pulse(
                self.camera_rtsp_url,
                pan,
                tilt,
                speed=speed,
                duration=0.24,
            )
            self.manager.set_ptz_error(self.camera_id, None)
        except Exception as exc:
            self.manager.set_ptz_error(self.camera_id, str(exc))

    def state(self) -> dict[str, Any]:
        settings = self.manager.settings_for(self.camera_id)
        return {
            "camera_id": self.camera_id,
            "status": self.status,
            "error": self.error,
            "detector": "yolox_tiny_onnx",
            "frame_width": self.frame_size[0],
            "frame_height": self.frame_size[1],
            "tracks": self.tracks_state,
            "auto_follow_enabled": bool(settings.get("auto_follow_enabled")),
            "selected_track_id": settings.get("selected_track_id"),
            "ptz_error": self.manager.ptz_errors.get(self.camera_id),
        }


class VisionManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.workers: dict[int, CameraVisionWorker] = {}
        self.runtime_settings: dict[int, dict[str, Any]] = {}
        self.ptz_errors: dict[int, str | None] = {}

    @property
    def available(self) -> bool:
        return CV_AVAILABLE

    @property
    def import_error(self) -> str | None:
        return CV_IMPORT_ERROR

    def start_camera(
        self,
        camera_id: int,
        camera_rtsp_url: str,
        stream_name: str,
        name: str,
    ) -> None:
        if not CV_AVAILABLE:
            return

        source_url = f"rtsp://127.0.0.1:8554/{stream_name}"
        with self.lock:
            existing = self.workers.get(camera_id)
            if (
                existing
                and existing.is_alive()
                and existing.source_url == source_url
                and existing.camera_rtsp_url == camera_rtsp_url
            ):
                return
            if existing:
                existing.stop()

            worker = CameraVisionWorker(
                self,
                camera_id,
                source_url,
                camera_rtsp_url,
                name,
            )
            self.workers[camera_id] = worker
            worker.start()

    def stop_camera(self, camera_id: int) -> None:
        with self.lock:
            worker = self.workers.pop(camera_id, None)
            if worker:
                worker.stop()

    def stop_all(self) -> None:
        for camera_id in list(self.workers):
            self.stop_camera(camera_id)

    def state(self, camera_id: int) -> dict[str, Any]:
        worker = self.workers.get(camera_id)
        if not CV_AVAILABLE:
            return {
                "camera_id": camera_id,
                "status": "unavailable",
                "error": CV_IMPORT_ERROR,
                "tracks": [],
            }
        if not worker:
            return {"camera_id": camera_id, "status": "stopped", "tracks": []}
        return worker.state()

    def settings_for(self, camera_id: int) -> dict[str, Any]:
        with self.lock:
            if camera_id not in self.runtime_settings:
                with connection() as conn:
                    row = conn.execute(
                        "SELECT * FROM camera_runtime_settings WHERE camera_id = ?",
                        (camera_id,),
                    ).fetchone()
                self.runtime_settings[camera_id] = (
                    dict(row)
                    if row
                    else {
                        "vision_enabled": 1,
                        "auto_follow_enabled": 0,
                        "selected_track_id": None,
                    }
                )
            return dict(self.runtime_settings[camera_id])

    def set_auto_follow(
        self,
        camera_id: int,
        enabled: bool,
        track_id: int | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with connection() as conn:
            conn.execute(
                """
                INSERT INTO camera_runtime_settings(
                    camera_id, vision_enabled, auto_follow_enabled,
                    selected_track_id, updated_at
                )
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET
                    auto_follow_enabled = excluded.auto_follow_enabled,
                    selected_track_id = excluded.selected_track_id,
                    updated_at = excluded.updated_at
                """,
                (camera_id, int(enabled), track_id, now),
            )
            conn.commit()

        with self.lock:
            current = self.runtime_settings.setdefault(camera_id, {"vision_enabled": 1})
            current.update(
                {
                    "auto_follow_enabled": int(enabled),
                    "selected_track_id": track_id,
                    "updated_at": now,
                }
            )

        if not enabled:
            self.ptz_errors[camera_id] = None
        return self.settings_for(camera_id)

    def set_ptz_error(self, camera_id: int, error: str | None) -> None:
        self.ptz_errors[camera_id] = error


manager = VisionManager()

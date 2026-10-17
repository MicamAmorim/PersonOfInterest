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
    VISION_TRACK_LOW_CONFIDENCE,
)
from .db import connection, utc_now
from .yolox_detector import YoloXPersonDetector

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    CV_AVAILABLE = True
    CV_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover
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
    smooth_cx: float | None = None
    smooth_cy: float | None = None
    smooth_w: float | None = None
    smooth_h: float | None = None
    control_valid: bool = False
    control_reason: str = "warming"


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


def _update_control_measurement(
    track: Track,
    bbox: tuple[int, int, int, int],
    confidence: float,
    frame_shape: tuple[int, ...],
    high_confidence: float,
) -> None:
    """Reject abrupt/partial boxes and smooth only trustworthy PTZ measurements."""
    height, width = frame_shape[:2]
    x, y, w, h = bbox
    cx, cy = _center(bbox)
    diag = max(1.0, math.hypot(width, height))

    if track.smooth_cx is None:
        track.smooth_cx, track.smooth_cy = cx, cy
        track.smooth_w, track.smooth_h = float(w), float(h)
        track.control_valid = track.hits >= 2 and confidence >= high_confidence
        track.control_reason = "ok" if track.control_valid else "warming"
        return

    jump = math.hypot(cx - track.smooth_cx, cy - track.smooth_cy) / diag
    old_area = max(1.0, float(track.smooth_w or w) * float(track.smooth_h or h))
    area_ratio = max(1.0, w * h) / old_area
    old_aspect = max(0.05, float(track.smooth_w or w) / max(1.0, float(track.smooth_h or h)))
    new_aspect = max(0.05, float(w) / max(1.0, float(h)))
    aspect_ratio = new_aspect / old_aspect
    edge = x <= width * 0.015 or y <= height * 0.015 or x + w >= width * 0.985 or y + h >= height * 0.985
    partial_edge = edge and area_ratio < 0.66

    valid, reason = True, "ok"
    if confidence < high_confidence:
        valid, reason = False, "low_confidence"
    elif track.hits < 2:
        valid, reason = False, "warming"
    elif jump > 0.22:
        valid, reason = False, "center_jump"
    elif not 0.35 <= area_ratio <= 2.8:
        valid, reason = False, "area_jump"
    elif not 0.45 <= aspect_ratio <= 2.2:
        valid, reason = False, "shape_jump"
    elif partial_edge:
        valid, reason = False, "partial_edge"

    track.control_valid = valid
    track.control_reason = reason
    if not valid:
        return

    alpha = 0.28 if jump < 0.07 else 0.42
    track.smooth_cx = (1 - alpha) * track.smooth_cx + alpha * cx
    track.smooth_cy = (1 - alpha) * track.smooth_cy + alpha * cy
    track.smooth_w = (1 - alpha) * float(track.smooth_w or w) + alpha * w
    track.smooth_h = (1 - alpha) * float(track.smooth_h or h) + alpha * h


class CentroidTracker:
    """Two-stage association inspired by ByteTrack.

    High-confidence detections can update or create tracks. Low-confidence
    detections can only rescue an existing track through blur/partial occlusion.
    """

    def __init__(self, high_confidence: float = VISION_PERSON_CONFIDENCE) -> None:
        self.next_id = 1
        self.tracks: dict[int, Track] = {}
        self.high_confidence = float(high_confidence)

    @staticmethod
    def _best_match(
        track: Track,
        candidate_indices: set[int],
        detections: list[tuple[tuple[int, int, int, int], float]],
        diag: float,
        *,
        relaxed: bool,
    ) -> int | None:
        best_idx: int | None = None
        best_score = -1.0
        tcx, tcy = _center(track.bbox)
        min_overlap = 0.06 if relaxed else 0.10
        max_distance = 0.11 if relaxed else 0.13
        for idx in candidate_indices:
            bbox, _ = detections[idx]
            dcx, dcy = _center(bbox)
            distance = math.hypot(tcx - dcx, tcy - dcy) / max(diag, 1.0)
            overlap = _iou(track.bbox, bbox)
            score = overlap * 1.7 + max(0.0, 0.24 - distance)
            if (overlap >= min_overlap or distance <= max_distance) and score > best_score:
                best_idx, best_score = idx, score
        return best_idx

    def update(self, detections: list[tuple[tuple[int, int, int, int], float]], frame_shape: tuple[int, ...]) -> list[Track]:
        height, width = frame_shape[:2]
        diag = math.hypot(width, height)
        high = {i for i, (_, conf) in enumerate(detections) if conf >= self.high_confidence}
        low = {i for i, (_, conf) in enumerate(detections) if conf < self.high_confidence}
        unmatched_tracks: list[Track] = []

        # Stage 1: normal/high-confidence association.
        for track in list(self.tracks.values()):
            idx = self._best_match(track, high, detections, diag, relaxed=False)
            if idx is None:
                unmatched_tracks.append(track)
                continue
            bbox, conf = detections[idx]
            high.remove(idx)
            track.bbox = bbox
            track.confidence = conf
            track.hits += 1
            track.missed = 0
            track.last_seen_monotonic = time.monotonic()
            _update_control_measurement(track, bbox, conf, frame_shape, self.high_confidence)

        # Stage 2: low-confidence boxes may preserve identity, but never drive PTZ
        # and never create a new person.
        still_unmatched: list[Track] = []
        for track in unmatched_tracks:
            idx = self._best_match(track, low, detections, diag, relaxed=True)
            if idx is None:
                still_unmatched.append(track)
                continue
            bbox, conf = detections[idx]
            low.remove(idx)
            track.bbox = bbox
            track.confidence = conf
            track.hits += 1
            track.missed = 0
            track.last_seen_monotonic = time.monotonic()
            _update_control_measurement(track, bbox, conf, frame_shape, self.high_confidence)

        for track in still_unmatched:
            track.missed += 1
            track.control_valid = False
            track.control_reason = "missed"
            if track.missed > 6:
                self.tracks.pop(track.id, None)

        # Only high-confidence unmatched detections are allowed to create tracks.
        for idx in high:
            bbox, conf = detections[idx]
            track = Track(self.next_id, bbox, conf)
            _update_control_measurement(track, bbox, conf, frame_shape, self.high_confidence)
            self.tracks[track.id] = track
            self.next_id += 1

        return [t for t in self.tracks.values() if t.missed <= 3]


class CameraVisionWorker(threading.Thread):
    def __init__(self, manager: "VisionManager", camera_id: int, source_url: str, camera_rtsp_url: str, camera_name: str) -> None:
        super().__init__(name=f"poi-vision-{camera_id}", daemon=True)
        self.manager = manager
        self.camera_id = camera_id
        self.source_url = source_url
        self.camera_rtsp_url = camera_rtsp_url
        self.camera_name = camera_name
        self.stop_event = threading.Event()
        self.tracker = CentroidTracker(VISION_PERSON_CONFIDENCE)
        self.last_event_at = 0.0
        self.last_follow_move = 0.0
        self.status = "starting"
        self.error: str | None = None
        self.frame_size = (0, 0)
        self.tracks_state: list[dict[str, Any]] = []
        self.target_lost_since: float | None = None
        self.home_returned_for_loss = False
        self.pan_active = False
        self.tilt_active = False

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:  # pragma: no cover
        if not CV_AVAILABLE:
            self.status = "unavailable"
            self.error = CV_IMPORT_ERROR
            return
        try:
            detector = YoloXPersonDetector(
                VISION_MODEL_PATH,
                confidence=VISION_PERSON_CONFIDENCE,
                low_confidence=VISION_TRACK_LOW_CONFIDENCE,
                nms_threshold=VISION_NMS_THRESHOLD,
            )
        except Exception as exc:
            self.status = "error"
            self.error = f"Falha ao carregar YOLOX ONNX: {exc}"
            return

        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
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

        tracks = self.tracker.update(detector.detect(frame), frame.shape)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(34, 34))
        face_boxes = [tuple(map(int, f)) for f in faces]

        for track in tracks:
            x, y, w, h = track.bbox
            associated = []
            for face in face_boxes:
                fx, fy, fw, fh = face
                cx, cy = fx + fw / 2, fy + fh / 2
                if x <= cx <= x + w and y <= cy <= y + h:
                    associated.append(face)
            had_face_before = track.has_face
            if associated:
                track.has_face = True
                track.face_count = max(track.face_count, len(associated))
            # Low-confidence rescued tracks preserve identity but do not create a
            # fresh event until a reliable detection has returned.
            if track.hits >= 2 and track.confidence >= VISION_PERSON_CONFIDENCE and track.event_id is None and time.monotonic() - self.last_event_at >= VISION_EVENT_COOLDOWN_SECONDS:
                track.event_id = self._save_event(frame, track, associated)
                self.last_event_at = time.monotonic()
            elif track.event_id and associated and not had_face_before:
                self._mark_face(track.event_id, len(associated))

        self.tracks_state = [
            {
                "track_id": t.id,
                "bbox": {"x": t.bbox[0] / width, "y": t.bbox[1] / height, "w": t.bbox[2] / width, "h": t.bbox[3] / height},
                "confidence": round(float(t.confidence), 3),
                "has_face": t.has_face,
                "face_count": t.face_count,
                "control_valid": t.control_valid,
                "control_reason": t.control_reason,
            }
            for t in tracks
        ]
        self._auto_follow(tracks, width, height)

    def _save_event(self, frame: Any, track: Track, faces: list[tuple[int, int, int, int]]) -> int | None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        folder = EVENTS_DIR / day / str(self.camera_id)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%H%M%S_%f")
        path = folder / f"track_{track.id}_{stamp}.jpg"
        annotated = frame.copy()
        x, y, w, h = track.bbox
        cv2.rectangle(annotated, (x, y), (x + w, y + h), (255, 255, 255), 2)
        cv2.putText(annotated, f"Person #{track.id}", (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        for fx, fy, fw, fh in faces:
            cv2.rectangle(annotated, (fx, fy), (fx + fw, fy + fh), (180, 180, 180), 1)
        if not cv2.imwrite(str(path), annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 86]):
            return None
        relative = str(path.relative_to(EVENTS_DIR)).replace("\\", "/")
        with connection() as conn:
            cursor = conn.execute(
                """INSERT INTO events(camera_id, track_id, event_type, has_face, face_count, confidence, snapshot_path, bbox_json, created_at)
                VALUES (?, ?, 'person', ?, ?, ?, ?, ?, ?)""",
                (self.camera_id, track.id, int(bool(faces)), len(faces), float(track.confidence), relative, json.dumps({"x": x, "y": y, "w": w, "h": h}), utc_now()),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def _mark_face(self, event_id: int, face_count: int) -> None:
        with connection() as conn:
            conn.execute("UPDATE events SET has_face = 1, face_count = MAX(face_count, ?) WHERE id = ?", (face_count, event_id))
            conn.commit()

    @staticmethod
    def _axis_command(error: float, active: bool) -> tuple[float, bool]:
        enter = 0.17
        exit_ = 0.10
        threshold = exit_ if active else enter
        if abs(error) < threshold:
            return 0.0, False
        return (1.0 if error > 0 else -1.0), True

    def _handle_lost_target(self, settings: dict[str, Any]) -> None:
        now = time.monotonic()
        if self.target_lost_since is None:
            self.target_lost_since = now
            return
        if now - self.target_lost_since < 3.0 or self.home_returned_for_loss:
            return
        if not settings.get("home_preset_set"):
            return
        self.home_returned_for_loss = True
        threading.Thread(target=self._return_home, daemon=True).start()

    def _auto_follow(self, tracks: list[Track], width: int, height: int) -> None:
        settings = self.manager.settings_for(self.camera_id)
        if not settings.get("auto_follow_enabled"):
            self.target_lost_since = None
            self.home_returned_for_loss = False
            self.pan_active = self.tilt_active = False
            return

        selected = settings.get("selected_track_id")
        if selected:
            target = next((t for t in tracks if t.id == selected and t.control_valid), None)
        else:
            valid = [t for t in tracks if t.control_valid]
            target = max(valid, key=lambda t: t.bbox[2] * t.bbox[3]) if valid else None

        if target is None or target.smooth_cx is None or target.smooth_cy is None:
            self.pan_active = self.tilt_active = False
            self._handle_lost_target(settings)
            return

        self.target_lost_since = None
        self.home_returned_for_loss = False
        dx = target.smooth_cx / width - 0.5
        dy = target.smooth_cy / height - 0.5
        pan, self.pan_active = self._axis_command(dx, self.pan_active)
        tilt, self.tilt_active = self._axis_command(-dy, self.tilt_active)
        if not (pan or tilt):
            return

        now = time.monotonic()
        if now - self.last_follow_move < 0.55:
            return
        error = max(abs(dx), abs(dy))
        speed = min(0.42, max(0.16, 0.16 + error * 0.55))
        duration = min(0.22, max(0.14, 0.13 + error * 0.18))
        self.last_follow_move = now
        threading.Thread(target=self._ptz_pulse, args=(pan, tilt, speed, duration), daemon=True).start()

    def _ptz_pulse(self, pan: float, tilt: float, speed: float, duration: float) -> None:
        try:
            ptz.pulse(self.camera_rtsp_url, pan, tilt, speed=speed, duration=duration, max_step=8, max_consecutive=6)
            self.manager.set_ptz_error(self.camera_id, None)
        except Exception as exc:
            self.manager.set_ptz_error(self.camera_id, str(exc))

    def _return_home(self) -> None:
        try:
            ptz.goto_home(self.camera_rtsp_url)
            self.manager.set_ptz_error(self.camera_id, None)
        except Exception as exc:
            self.manager.set_ptz_error(self.camera_id, str(exc))

    def state(self) -> dict[str, Any]:
        settings = self.manager.settings_for(self.camera_id)
        lost_for = 0.0 if self.target_lost_since is None else max(0.0, time.monotonic() - self.target_lost_since)
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
            "home_preset_set": bool(settings.get("home_preset_set")),
            "target_lost_seconds": round(lost_for, 2),
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

    def start_camera(self, camera_id: int, camera_rtsp_url: str, stream_name: str, name: str) -> None:
        if not CV_AVAILABLE:
            return
        source_url = f"rtsp://127.0.0.1:8554/{stream_name}"
        with self.lock:
            existing = self.workers.get(camera_id)
            if existing and existing.is_alive() and existing.source_url == source_url and existing.camera_rtsp_url == camera_rtsp_url:
                return
            if existing:
                existing.stop()
            worker = CameraVisionWorker(self, camera_id, source_url, camera_rtsp_url, name)
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
            return {"camera_id": camera_id, "status": "unavailable", "error": CV_IMPORT_ERROR, "tracks": []}
        if not worker:
            return {"camera_id": camera_id, "status": "stopped", "tracks": []}
        return worker.state()

    def settings_for(self, camera_id: int) -> dict[str, Any]:
        with self.lock:
            if camera_id not in self.runtime_settings:
                with connection() as conn:
                    row = conn.execute("SELECT * FROM camera_runtime_settings WHERE camera_id = ?", (camera_id,)).fetchone()
                self.runtime_settings[camera_id] = dict(row) if row else {
                    "vision_enabled": 1,
                    "auto_follow_enabled": 0,
                    "selected_track_id": None,
                    "home_preset_set": 0,
                }
            return dict(self.runtime_settings[camera_id])

    def set_auto_follow(self, camera_id: int, enabled: bool, track_id: int | None = None) -> dict[str, Any]:
        now = utc_now()
        with connection() as conn:
            conn.execute(
                """INSERT INTO camera_runtime_settings(camera_id, vision_enabled, auto_follow_enabled, selected_track_id, updated_at)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET auto_follow_enabled = excluded.auto_follow_enabled, selected_track_id = excluded.selected_track_id, updated_at = excluded.updated_at""",
                (camera_id, int(enabled), track_id, now),
            )
            conn.commit()
        with self.lock:
            current = self.runtime_settings.setdefault(camera_id, {"vision_enabled": 1, "home_preset_set": 0})
            current.update({"auto_follow_enabled": int(enabled), "selected_track_id": track_id, "updated_at": now})
        if not enabled:
            self.ptz_errors[camera_id] = None
        return self.settings_for(camera_id)

    def set_home_preset(self, camera_id: int, is_set: bool) -> dict[str, Any]:
        now = utc_now()
        with connection() as conn:
            conn.execute(
                """INSERT INTO camera_runtime_settings(camera_id, home_preset_set, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET home_preset_set = excluded.home_preset_set, updated_at = excluded.updated_at""",
                (camera_id, int(is_set), now),
            )
            conn.commit()
        with self.lock:
            current = self.runtime_settings.setdefault(camera_id, {"vision_enabled": 1, "auto_follow_enabled": 0, "selected_track_id": None})
            current.update({"home_preset_set": int(is_set), "updated_at": now})
        return self.settings_for(camera_id)

    def set_ptz_error(self, camera_id: int, error: str | None) -> None:
        self.ptz_errors[camera_id] = error


manager = VisionManager()

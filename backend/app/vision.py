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
    VISION_AUTOFOLLOW_MAX_SPEED,
    VISION_EVENT_COOLDOWN_SECONDS,
    VISION_FACE_SEARCH_AFTER,
    VISION_FACE_SEARCH_MAX_SPEED,
    VISION_MAX_TARGET_SPEED,
    VISION_MAX_WIDTH,
    VISION_MODEL_PATH,
    VISION_NMS_THRESHOLD,
    VISION_PERSON_CONFIDENCE,
    VISION_PREDICTION_HORIZON,
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
    face_cx: float | None = None
    face_cy: float | None = None
    last_face_monotonic: float | None = None
    face_seen_now: bool = False
    event_id: int | None = None
    created_monotonic: float = field(default_factory=time.monotonic)
    last_seen_monotonic: float = field(default_factory=time.monotonic)
    smooth_cx: float | None = None
    smooth_cy: float | None = None
    smooth_w: float | None = None
    smooth_h: float | None = None
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    last_control_monotonic: float | None = None
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


def _clamp_vector(x: float, y: float, maximum: float) -> tuple[float, float]:
    magnitude = math.hypot(x, y)
    if magnitude <= maximum or magnitude <= 1e-9:
        return x, y
    scale = maximum / magnitude
    return x * scale, y * scale


def _update_control_measurement(
    track: Track,
    bbox: tuple[int, int, int, int],
    confidence: float,
    frame_shape: tuple[int, ...],
    high_confidence: float,
) -> None:
    height, width = frame_shape[:2]
    x, y, w, h = bbox
    cx, cy = _center(bbox)
    diag = max(1.0, math.hypot(width, height))
    now = time.monotonic()

    if track.smooth_cx is None:
        track.smooth_cx, track.smooth_cy = cx, cy
        track.smooth_w, track.smooth_h = float(w), float(h)
        track.last_control_monotonic = now
        track.velocity_x = track.velocity_y = 0.0
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
        # A weak or partial box may keep identity but cannot inject a sudden
        # position/velocity jump into the PTZ controller.
        track.velocity_x *= 0.72
        track.velocity_y *= 0.72
        return

    previous_x = float(track.smooth_cx)
    previous_y = float(track.smooth_cy)
    dt = max(0.05, min(1.2, now - float(track.last_control_monotonic or now)))
    alpha = 0.31 if jump < 0.07 else 0.48
    track.smooth_cx = (1 - alpha) * previous_x + alpha * cx
    track.smooth_cy = (1 - alpha) * previous_y + alpha * cy
    track.smooth_w = (1 - alpha) * float(track.smooth_w or w) + alpha * w
    track.smooth_h = (1 - alpha) * float(track.smooth_h or h) + alpha * h

    raw_vx = ((track.smooth_cx - previous_x) / max(1.0, width)) / dt
    raw_vy = ((track.smooth_cy - previous_y) / max(1.0, height)) / dt
    raw_vx, raw_vy = _clamp_vector(raw_vx, raw_vy, VISION_MAX_TARGET_SPEED)
    beta = 0.40 if track.hits >= 4 else 0.28
    track.velocity_x = (1 - beta) * track.velocity_x + beta * raw_vx
    track.velocity_y = (1 - beta) * track.velocity_y + beta * raw_vy
    track.velocity_x, track.velocity_y = _clamp_vector(track.velocity_x, track.velocity_y, VISION_MAX_TARGET_SPEED)
    track.last_control_monotonic = now


class CentroidTracker:
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
        max_distance = 0.12 if relaxed else 0.14
        for idx in candidate_indices:
            bbox, _ = detections[idx]
            dcx, dcy = _center(bbox)
            distance = math.hypot(tcx - dcx, tcy - dcy) / max(diag, 1.0)
            overlap = _iou(track.bbox, bbox)
            score = overlap * 1.7 + max(0.0, 0.26 - distance)
            if (overlap >= min_overlap or distance <= max_distance) and score > best_score:
                best_idx, best_score = idx, score
        return best_idx

    def update(self, detections: list[tuple[tuple[int, int, int, int], float]], frame_shape: tuple[int, ...]) -> list[Track]:
        _, width = frame_shape[:2]
        diag = math.hypot(width, frame_shape[0])
        high = {i for i, (_, conf) in enumerate(detections) if conf >= self.high_confidence}
        low = {i for i, (_, conf) in enumerate(detections) if conf < self.high_confidence}
        unmatched_tracks: list[Track] = []

        for track in list(self.tracks.values()):
            idx = self._best_match(track, high, detections, diag, relaxed=False)
            if idx is None:
                unmatched_tracks.append(track)
                continue
            bbox, conf = detections[idx]
            high.remove(idx)
            track.bbox, track.confidence = bbox, conf
            track.hits += 1
            track.missed = 0
            track.last_seen_monotonic = time.monotonic()
            _update_control_measurement(track, bbox, conf, frame_shape, self.high_confidence)

        still_unmatched: list[Track] = []
        for track in unmatched_tracks:
            idx = self._best_match(track, low, detections, diag, relaxed=True)
            if idx is None:
                still_unmatched.append(track)
                continue
            bbox, conf = detections[idx]
            low.remove(idx)
            track.bbox, track.confidence = bbox, conf
            track.hits += 1
            track.missed = 0
            track.last_seen_monotonic = time.monotonic()
            _update_control_measurement(track, bbox, conf, frame_shape, self.high_confidence)

        for track in still_unmatched:
            track.missed += 1
            track.control_valid = False
            track.control_reason = "missed"
            track.velocity_x *= 0.68
            track.velocity_y *= 0.68
            track.face_seen_now = False
            if track.missed > 6:
                self.tracks.pop(track.id, None)

        for idx in high:
            bbox, conf = detections[idx]
            track = Track(self.next_id, bbox, conf)
            _update_control_measurement(track, bbox, conf, frame_shape, self.high_confidence)
            self.tracks[track.id] = track
            self.next_id += 1

        return [t for t in self.tracks.values() if t.missed <= 3]


class LatestFrameReader:
    """Continuously drain RTSP so inference always receives the newest frame.

    OpenCV/FFmpeg often buffers RTSP even when CAP_PROP_BUFFERSIZE is ignored.
    Reading on a dedicated thread and keeping only one frame prevents inference
    from working through stale queued frames, which is critical for PTZ control.
    """

    def __init__(self, source_url: str) -> None:
        self.cap = cv2.VideoCapture(source_url, cv2.CAP_FFMPEG)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.frame: Any | None = None
        self.frame_at = 0.0
        self.seq = 0
        self.failed = False
        self.thread = threading.Thread(target=self._run, name="poi-frame-drain", daemon=True)

    @property
    def opened(self) -> bool:
        return bool(self.cap.isOpened())

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:  # pragma: no cover - camera boundary
        while not self.stop_event.is_set():
            ok, frame = self.cap.read()
            if not ok or frame is None:
                self.failed = True
                return
            with self.lock:
                self.frame = frame
                self.frame_at = time.monotonic()
                self.seq += 1

    def latest(self, previous_seq: int) -> tuple[Any | None, int, float]:
        with self.lock:
            if self.frame is None or self.seq == previous_seq:
                return None, previous_seq, self.frame_at
            return self.frame.copy(), self.seq, self.frame_at

    def close(self) -> None:
        self.stop_event.set()
        self.cap.release()
        if self.thread.is_alive():
            self.thread.join(timeout=0.5)


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
        self.last_face_search_move = 0.0
        self.follow_speed = 0.0
        self.capture_latency_ms = 0.0
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
        target_interval = 1.0 / max(0.5, VISION_PROCESS_FPS)
        while not self.stop_event.is_set():
            reader = LatestFrameReader(self.source_url)
            if not reader.opened:
                reader.close()
                self.status = "error"
                self.error = "Não foi possível abrir o restream local para visão computacional"
                time.sleep(1.0)
                continue

            reader.start()
            self.status, self.error = "running", None
            last_seq = -1
            last_processed = 0.0
            try:
                while not self.stop_event.is_set() and not reader.failed:
                    now = time.monotonic()
                    wait = target_interval - (now - last_processed)
                    if wait > 0:
                        time.sleep(min(0.02, wait))
                        continue
                    frame, seq, frame_at = reader.latest(last_seq)
                    if frame is None:
                        time.sleep(0.005)
                        continue
                    last_seq = seq
                    last_processed = time.monotonic()
                    self.capture_latency_ms = max(0.0, (last_processed - frame_at) * 1000.0)
                    self._process(frame, detector, face_cascade)
            finally:
                reader.close()
            if not self.stop_event.is_set():
                self.status = "reconnecting"
                time.sleep(0.35)

    def _faces_for_track(self, gray: Any, track: Track, width: int, height: int, face_cascade: Any) -> list[tuple[int, int, int, int]]:
        x, y, w, h = track.bbox
        # Search well above a partial body box too: if only legs are visible, the
        # face may enter the frame just above the current detection after PTZ tilts.
        x1 = max(0, x - int(w * 0.18))
        x2 = min(width, x + w + int(w * 0.18))
        y1 = max(0, y - int(h * 1.10))
        y2 = min(height, y + int(h * 0.62))
        if x2 - x1 < 34 or y2 - y1 < 34:
            return []
        roi = gray[y1:y2, x1:x2]
        local = face_cascade.detectMultiScale(roi, scaleFactor=1.12, minNeighbors=5, minSize=(28, 28))
        return [(x1 + int(fx), y1 + int(fy), int(fw), int(fh)) for fx, fy, fw, fh in local]

    def _process(self, frame: Any, detector: YoloXPersonDetector, face_cascade: Any) -> None:
        h0, w0 = frame.shape[:2]
        if w0 > VISION_MAX_WIDTH:
            scale = VISION_MAX_WIDTH / float(w0)
            frame = cv2.resize(frame, (VISION_MAX_WIDTH, int(h0 * scale)))
        height, width = frame.shape[:2]
        self.frame_size = (width, height)
        tracks = self.tracker.update(detector.detect(frame), frame.shape)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        now = time.monotonic()
        for track in tracks:
            track.face_seen_now = False
            associated = self._faces_for_track(gray, track, width, height, face_cascade)
            had_face_before = track.has_face
            if associated:
                # Prefer the largest face if a ROI happens to contain another person.
                fx, fy, fw, fh = max(associated, key=lambda f: f[2] * f[3])
                measured_x, measured_y = fx + fw / 2, fy + fh / 2
                if track.face_cx is None:
                    track.face_cx, track.face_cy = measured_x, measured_y
                else:
                    track.face_cx = 0.55 * track.face_cx + 0.45 * measured_x
                    track.face_cy = 0.55 * float(track.face_cy or measured_y) + 0.45 * measured_y
                track.last_face_monotonic = now
                track.face_seen_now = True
                track.has_face = True
                track.face_count = max(track.face_count, len(associated))

            if track.hits >= 2 and track.confidence >= VISION_PERSON_CONFIDENCE and track.event_id is None and now - self.last_event_at >= VISION_EVENT_COOLDOWN_SECONDS:
                track.event_id = self._save_event(frame, track, associated)
                self.last_event_at = now
            elif track.event_id and associated and not had_face_before:
                self._mark_face(track.event_id, len(associated))

        horizon = max(0.0, min(0.7, VISION_PREDICTION_HORIZON))
        self.tracks_state = [
            {
                "track_id": t.id,
                "bbox": {"x": t.bbox[0] / width, "y": t.bbox[1] / height, "w": t.bbox[2] / width, "h": t.bbox[3] / height},
                "confidence": round(float(t.confidence), 3),
                "has_face": t.has_face,
                "face_seen_now": t.face_seen_now,
                "face_count": t.face_count,
                "control_valid": t.control_valid,
                "control_reason": t.control_reason,
                "face_search": self._needs_face_search(t, height),
                "velocity": {"x": round(t.velocity_x, 3), "y": round(t.velocity_y, 3)},
                "predicted_center": (
                    {
                        "x": round(max(0.0, min(1.0, (t.smooth_cx or 0.0) / width + t.velocity_x * horizon)), 3),
                        "y": round(max(0.0, min(1.0, (t.smooth_cy or 0.0) / height + t.velocity_y * horizon)), 3),
                    }
                    if t.smooth_cx is not None and t.smooth_cy is not None else None
                ),
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
        threshold = 0.085 if active else 0.145
        if abs(error) < threshold:
            return 0.0, False
        return (1.0 if error > 0 else -1.0), True

    def _needs_face_search(self, track: Track, height: int) -> bool:
        if track.face_seen_now:
            return False
        no_face_since = track.last_face_monotonic or track.created_monotonic
        if time.monotonic() - no_face_since < VISION_FACE_SEARCH_AFTER:
            return False
        _, y, _, h = track.bbox
        bottom = y + h
        lower_or_partial = y > height * 0.36 or bottom > height * 0.90
        return track.confidence >= VISION_PERSON_CONFIDENCE and track.hits >= 3 and lower_or_partial

    def _handle_lost_target(self, settings: dict[str, Any]) -> None:
        now = time.monotonic()
        if self.target_lost_since is None:
            self.target_lost_since = now
            return
        if now - self.target_lost_since < 3.0 or self.home_returned_for_loss or not settings.get("home_preset_set"):
            return
        self.home_returned_for_loss = True
        threading.Thread(target=self._return_home, daemon=True).start()

    def _partial_lower_body_recovery(self, target: Track, height: int, camera_ceiling: float) -> bool:
        """For a trustworthy lower-body fragment, search upward only.

        We intentionally do not use the fragment's horizontal center or velocity:
        this prevents a legs-only/edge box from throwing pan control sideways.
        """
        if target.control_reason != "partial_edge" or not self._needs_face_search(target, height):
            return False
        _, y, _, h = target.bbox
        if y + h < height * 0.92:
            return False
        now = time.monotonic()
        if now - self.last_face_search_move < 0.34:
            return True
        self.last_face_search_move = now
        speed = min(camera_ceiling, VISION_FACE_SEARCH_MAX_SPEED)
        threading.Thread(target=self._ptz_pulse, args=(0.0, 1.0, speed, 0.10), daemon=True).start()
        return True

    def _auto_follow(self, tracks: list[Track], width: int, height: int) -> None:
        settings = self.manager.settings_for(self.camera_id)
        if not settings.get("auto_follow_enabled"):
            self.target_lost_since = None
            self.home_returned_for_loss = False
            self.pan_active = self.tilt_active = False
            self.follow_speed = 0.0
            return

        hard_ceiling = max(0.20, min(0.90, VISION_AUTOFOLLOW_MAX_SPEED))
        camera_ceiling = max(0.20, min(hard_ceiling, float(settings.get("autofollow_max_speed", 0.65))))
        selected = settings.get("selected_track_id")
        if selected:
            raw_target = next((t for t in tracks if t.id == selected), None)
        else:
            candidates = [t for t in tracks if t.control_valid or t.control_reason == "partial_edge"]
            raw_target = max(candidates, key=lambda t: t.bbox[2] * t.bbox[3]) if candidates else None

        if raw_target is not None and self._partial_lower_body_recovery(raw_target, height, camera_ceiling):
            self.target_lost_since = None
            self.home_returned_for_loss = False
            self.pan_active = False
            return

        target = raw_target if raw_target is not None and raw_target.control_valid else None
        if target is None or target.smooth_cx is None or target.smooth_cy is None:
            self.pan_active = self.tilt_active = False
            self.follow_speed *= 0.65
            self._handle_lost_target(settings)
            return

        self.target_lost_since = None
        self.home_returned_for_loss = False
        horizon = max(0.0, min(0.7, VISION_PREDICTION_HORIZON))

        # Horizontal aim stays at body/face center. Vertically, favor the upper
        # torso; if a face was just detected, use its actual center. This both
        # keeps faces in frame and avoids centering the camera on a person's legs.
        current_x = target.smooth_cx / max(1.0, width)
        face_recent = target.last_face_monotonic is not None and time.monotonic() - target.last_face_monotonic < 0.85
        if face_recent and target.face_cx is not None and target.face_cy is not None:
            current_x = 0.72 * current_x + 0.28 * (target.face_cx / max(1.0, width))
            current_y = target.face_cy / max(1.0, height)
        else:
            upper_anchor = float(target.smooth_cy) - 0.20 * float(target.smooth_h or 0.0)
            if self._needs_face_search(target, height):
                upper_anchor -= min(height * 0.08, float(target.smooth_h or 0.0) * 0.18)
            current_y = upper_anchor / max(1.0, height)

        predicted_x = max(0.03, min(0.97, current_x + target.velocity_x * horizon))
        predicted_y = max(0.03, min(0.97, current_y + target.velocity_y * horizon))
        dx, dy = predicted_x - 0.5, predicted_y - 0.5
        pan, self.pan_active = self._axis_command(dx, self.pan_active)
        tilt, self.tilt_active = self._axis_command(-dy, self.tilt_active)
        if not (pan or tilt):
            self.follow_speed *= 0.55
            return

        motion = min(VISION_MAX_TARGET_SPEED, math.hypot(target.velocity_x, target.velocity_y))
        error = max(abs(dx), abs(dy))
        requested_speed = 0.14 + error * 0.68 + min(0.34, motion * 0.38)
        requested_speed = max(0.16, min(camera_ceiling, requested_speed))

        # Faster response than v0.2.3, but still slew-limited and bounded by the
        # per-camera maximum. Fresh-frame draining removes most apparent delay;
        # this term handles the remaining motor/network latency.
        blended = 0.42 * self.follow_speed + 0.58 * requested_speed if self.follow_speed else requested_speed
        max_delta = 0.10 + min(0.11, motion * 0.11)
        if self.follow_speed:
            blended = max(self.follow_speed - max_delta, min(self.follow_speed + max_delta, blended))
        self.follow_speed = max(0.15, min(camera_ceiling, blended))

        min_interval = max(0.18, 0.31 - min(0.11, motion * 0.12))
        now = time.monotonic()
        if now - self.last_follow_move < min_interval:
            return
        duration = min(0.16, max(0.08, 0.08 + error * 0.12))
        self.last_follow_move = now
        threading.Thread(target=self._ptz_pulse, args=(pan, tilt, self.follow_speed, duration), daemon=True).start()

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
            "autofollow_max_speed": float(settings.get("autofollow_max_speed", 0.65)),
            "target_lost_seconds": round(lost_for, 2),
            "follow_speed": round(self.follow_speed, 3),
            "prediction_horizon": VISION_PREDICTION_HORIZON,
            "capture_latency_ms": round(self.capture_latency_ms, 1),
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
            settings = self.settings_for(camera_id)
            return {"camera_id": camera_id, "status": "stopped", "tracks": [], "autofollow_max_speed": float(settings.get("autofollow_max_speed", 0.65))}
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
                    "autofollow_max_speed": 0.65,
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
            current = self.runtime_settings.setdefault(camera_id, {"vision_enabled": 1, "home_preset_set": 0, "autofollow_max_speed": 0.65})
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
            current = self.runtime_settings.setdefault(camera_id, {"vision_enabled": 1, "auto_follow_enabled": 0, "selected_track_id": None, "autofollow_max_speed": 0.65})
            current.update({"home_preset_set": int(is_set), "updated_at": now})
        return self.settings_for(camera_id)

    def set_autofollow_max_speed(self, camera_id: int, value: float) -> dict[str, Any]:
        value = max(0.20, min(0.90, float(value)))
        now = utc_now()
        with connection() as conn:
            conn.execute(
                """INSERT INTO camera_runtime_settings(camera_id, autofollow_max_speed, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET autofollow_max_speed = excluded.autofollow_max_speed, updated_at = excluded.updated_at""",
                (camera_id, value, now),
            )
            conn.commit()
        with self.lock:
            current = self.runtime_settings.setdefault(camera_id, {"vision_enabled": 1, "auto_follow_enabled": 0, "selected_track_id": None, "home_preset_set": 0})
            current.update({"autofollow_max_speed": value, "updated_at": now})
        return self.settings_for(camera_id)

    def set_ptz_error(self, camera_id: int, error: str | None) -> None:
        self.ptz_errors[camera_id] = error


manager = VisionManager()

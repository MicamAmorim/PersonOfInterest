from __future__ import annotations

import json
import math
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import body_identity as bi
from . import db
from . import identity as fi
from . import vision
from .config import (
    BODY_REID_MARGIN,
    BODY_REID_THRESHOLD,
    DATA_DIR,
    EVENTS_DIR,
    FACES_DIR,
    VISION_MAX_WIDTH,
    VISION_PERSON_CONFIDENCE,
    VISION_PROCESS_FPS,
)
from .db import connection, utc_now


V5_TRACK_REASSOC_SECONDS = 4.5
V5_TRACK_VISIBLE_MISSES = 3
V5_OBSERVATION_INTERVAL = 0.45
V5_BODY_INTERVAL = 0.70
V5_MAX_BODY_OBSERVATIONS = 8
V5_MAX_TRACK_OBSERVATIONS = 24
V5_BODY_TRUST_MIN_SUPPORT = 3
V5_BODY_TRUST_MIN_STABILITY = 0.82
V5_BODY_TRUST_MIN_QUALITY = 0.43
V5_IDENTITY_SETTLE_SECONDS = 1.25
BODY_ANCHORS_DIR = DATA_DIR / "body_anchors"

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False


def _columns(conn: Any, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn: Any, table: str, name: str, ddl: str) -> None:
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        with connection() as conn:
            tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "events" not in tables or "body_samples" not in tables:
                return

            _ensure_column(conn, "events", "trigger_snapshot_path", "trigger_snapshot_path TEXT")
            _ensure_column(conn, "events", "best_snapshot_path", "best_snapshot_path TEXT")
            _ensure_column(conn, "events", "last_seen_at", "last_seen_at TEXT")
            _ensure_column(conn, "events", "ended_at", "ended_at TEXT")
            _ensure_column(conn, "events", "observation_count", "observation_count INTEGER NOT NULL DEFAULT 0")
            _ensure_column(conn, "events", "best_frame_quality", "best_frame_quality REAL NOT NULL DEFAULT 0")
            _ensure_column(conn, "events", "best_face_quality", "best_face_quality REAL NOT NULL DEFAULT 0")
            _ensure_column(conn, "events", "best_body_quality", "best_body_quality REAL NOT NULL DEFAULT 0")
            _ensure_column(conn, "events", "identity_origin", "identity_origin TEXT NOT NULL DEFAULT 'vision'")
            _ensure_column(conn, "events", "assistant_eligible", "assistant_eligible INTEGER NOT NULL DEFAULT 1")
            _ensure_column(conn, "events", "track_status", "track_status TEXT NOT NULL DEFAULT 'active'")
            _ensure_column(conn, "events", "track_session", "track_session TEXT")

            _ensure_column(conn, "body_samples", "trusted", "trusted INTEGER NOT NULL DEFAULT 0")
            _ensure_column(conn, "body_samples", "active", "active INTEGER NOT NULL DEFAULT 1")
            _ensure_column(conn, "body_samples", "temporal_support", "temporal_support INTEGER NOT NULL DEFAULT 1")
            _ensure_column(conn, "body_samples", "track_id", "track_id INTEGER")
            _ensure_column(conn, "body_samples", "stability", "stability REAL")

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS track_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    camera_id INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    frame_seq INTEGER NOT NULL,
                    bbox_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    body_quality REAL NOT NULL DEFAULT 0,
                    face_quality REAL NOT NULL DEFAULT 0,
                    is_best_frame INTEGER NOT NULL DEFAULT 0,
                    is_best_body INTEGER NOT NULL DEFAULT 0,
                    is_best_face INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
                    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_track_obs_event_created
                    ON track_observations(event_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS body_track_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    camera_id INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    embedding BLOB NOT NULL,
                    quality REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
                    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_body_track_obs_event_quality
                    ON body_track_observations(event_id, quality DESC);

                CREATE TABLE IF NOT EXISTS person_face_anchors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id INTEGER NOT NULL,
                    embedding BLOB NOT NULL,
                    crop_path TEXT,
                    quality REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_face_anchors_person_active
                    ON person_face_anchors(person_id, active);

                CREATE TABLE IF NOT EXISTS person_body_anchors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id INTEGER NOT NULL,
                    embedding BLOB NOT NULL,
                    crop_path TEXT,
                    quality REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_body_anchors_person_active
                    ON person_body_anchors(person_id, active);
                """
            )
            # Historical manual confirmation remains trusted. Automatic face-linked
            # body crops are quarantined until a temporally stable track promotes them.
            conn.execute(
                """UPDATE body_samples SET trusted = 1, active = 1
                WHERE verified = 1 AND person_id IS NOT NULL
                  AND (source LIKE '%manual%' OR source = 'manual_verified')"""
            )
            conn.execute(
                """UPDATE body_samples SET trusted = 0
                WHERE verified = 1 AND person_id IS NOT NULL
                  AND source LIKE 'face_verified%' AND source NOT LIKE '%manual%'"""
            )
            conn.execute("UPDATE events SET trigger_snapshot_path = snapshot_path WHERE trigger_snapshot_path IS NULL")
            conn.execute("UPDATE events SET best_snapshot_path = snapshot_path WHERE best_snapshot_path IS NULL")
            conn.execute("UPDATE events SET last_seen_at = created_at WHERE last_seen_at IS NULL")
            conn.commit()
        BODY_ANCHORS_DIR.mkdir(parents=True, exist_ok=True)
        _SCHEMA_READY = True


def _center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    x, y, w, h = box
    return x + w / 2.0, y + h / 2.0


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def _normalize(vector: Any) -> Any:
    vector = bi.np.asarray(vector, dtype=bi.np.float32).reshape(-1)
    norm = float(bi.np.linalg.norm(vector))
    return vector / max(norm, 1e-9)


def aggregate_temporal_body(observations: list[tuple[Any, float, float]]) -> tuple[Any | None, float, int, float]:
    """Robustly aggregate several body observations from one physical track.

    Consecutive crops are first combined, then observations that disagree with
    the track centroid are discarded. The returned stability describes temporal
    self-consistency, not identity certainty.
    """
    if bi.np is None or not observations:
        return None, 0.0, 0, 0.0
    ordered = sorted(observations, key=lambda item: float(item[1]), reverse=True)[:V5_MAX_BODY_OBSERVATIONS]
    vectors = [_normalize(item[0]) for item in ordered]
    weights = bi.np.asarray([max(0.15, float(item[1])) ** 2 for item in ordered], dtype=bi.np.float32)
    matrix = bi.np.stack(vectors, axis=0)
    centroid = _normalize((matrix * weights[:, None]).sum(axis=0))
    similarities = matrix @ centroid
    median = float(bi.np.median(similarities))
    cutoff = max(0.58, median - 0.08)
    keep = similarities >= cutoff
    if not bool(keep.any()):
        keep[:] = True
    kept = matrix[keep]
    kept_weights = weights[keep]
    centroid = _normalize((kept * kept_weights[:, None]).sum(axis=0))
    final_sims = kept @ centroid
    stability = float(final_sims.mean()) if len(final_sims) else 0.0
    kept_qualities = [float(ordered[i][1]) for i, flag in enumerate(keep.tolist()) if flag]
    mean_quality = sum(kept_qualities) / max(1, len(kept_qualities))
    quality = max(0.0, min(1.0, mean_quality * (0.72 + 0.28 * max(0.0, stability))))
    return centroid, quality, int(len(kept)), max(0.0, min(1.0, stability))


@dataclass(slots=True)
class PersistentTrack:
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
    session_key: str = field(default_factory=lambda: uuid.uuid4().hex)
    first_seen_utc: str = field(default_factory=utc_now)
    observation_count: int = 0
    best_frame_quality: float = 0.0
    best_body_quality: float = 0.0
    best_face_quality: float = 0.0
    trigger_snapshot_path: str | None = None
    best_snapshot_path: str | None = None
    last_faces: list[tuple[int, int, int, int]] = field(default_factory=list)
    body_observations: list[tuple[Any, float, float]] = field(default_factory=list)
    last_body_embed_monotonic: float = 0.0
    last_observation_save_monotonic: float = 0.0
    last_persist_monotonic: float = 0.0
    trusted_body_person_id: int | None = None


class PersistentCentroidTracker:
    """Short-term persistent tracker with predictive lost-track reassociation."""

    def __init__(self, high_confidence: float = VISION_PERSON_CONFIDENCE) -> None:
        self.next_id = 1
        self.tracks: dict[int, PersistentTrack] = {}
        self.high_confidence = float(high_confidence)
        self.max_missed = max(8, int(round(max(1.0, VISION_PROCESS_FPS) * V5_TRACK_REASSOC_SECONDS)))
        self.just_ended: list[PersistentTrack] = []

    @staticmethod
    def _pair_score(track: PersistentTrack, bbox: tuple[int, int, int, int], conf: float, diag: float, width: int, height: int) -> float | None:
        tcx, tcy = _center(track.bbox)
        elapsed = max(0.0, time.monotonic() - track.last_seen_monotonic)
        predicted_x = tcx + track.velocity_x * width * min(0.8, elapsed)
        predicted_y = tcy + track.velocity_y * height * min(0.8, elapsed)
        dcx, dcy = _center(bbox)
        distance = math.hypot(predicted_x - dcx, predicted_y - dcy) / max(1.0, diag)
        overlap = _iou(track.bbox, bbox)
        _, _, tw, th = track.bbox
        _, _, dw, dh = bbox
        area_ratio = max(1.0, float(dw * dh)) / max(1.0, float(tw * th))
        shape_ratio = (float(dw) / max(1.0, dh)) / max(0.05, float(tw) / max(1.0, th))
        relaxed = min(0.30, 0.14 + 0.018 * track.missed)
        if distance > relaxed and overlap < (0.035 if track.missed else 0.075):
            return None
        if not 0.16 <= area_ratio <= 6.2 or not 0.25 <= shape_ratio <= 4.0:
            return None
        confidence_bonus = max(0.0, min(1.0, conf)) * 0.08
        continuity_bonus = max(0.0, 0.16 - 0.012 * track.missed)
        return overlap * 1.65 + max(0.0, relaxed - distance) * 2.1 + confidence_bonus + continuity_bonus

    def update(self, detections: list[tuple[tuple[int, int, int, int], float]], frame_shape: tuple[int, ...]) -> list[PersistentTrack]:
        height, width = frame_shape[:2]
        diag = math.hypot(width, height)
        self.just_ended = []
        candidate_pairs: list[tuple[float, int, int]] = []
        for track_id, track in self.tracks.items():
            for index, (bbox, conf) in enumerate(detections):
                score = self._pair_score(track, bbox, conf, diag, width, height)
                if score is not None:
                    candidate_pairs.append((score, track_id, index))
        candidate_pairs.sort(reverse=True)
        assigned_tracks: set[int] = set()
        assigned_detections: set[int] = set()
        for _, track_id, index in candidate_pairs:
            if track_id in assigned_tracks or index in assigned_detections:
                continue
            track = self.tracks.get(track_id)
            if track is None:
                continue
            bbox, conf = detections[index]
            # Low-confidence detections may maintain an existing track, but never
            # create a new one by themselves.
            if conf < self.high_confidence and track.missed == 0 and track.hits < 2:
                continue
            track.bbox = bbox
            track.confidence = conf
            track.hits += 1
            track.missed = 0
            track.last_seen_monotonic = time.monotonic()
            vision._update_control_measurement(track, bbox, conf, frame_shape, self.high_confidence)
            assigned_tracks.add(track_id)
            assigned_detections.add(index)

        for track_id, track in list(self.tracks.items()):
            if track_id in assigned_tracks:
                continue
            track.missed += 1
            track.control_valid = False
            track.control_reason = "missed"
            track.velocity_x *= 0.72
            track.velocity_y *= 0.72
            track.face_seen_now = False
            track.last_faces = []
            if track.missed > self.max_missed:
                self.just_ended.append(track)
                self.tracks.pop(track_id, None)

        for index, (bbox, conf) in enumerate(detections):
            if index in assigned_detections or conf < self.high_confidence:
                continue
            track = PersistentTrack(self.next_id, bbox, conf)
            vision._update_control_measurement(track, bbox, conf, frame_shape, self.high_confidence)
            self.tracks[track.id] = track
            self.next_id += 1

        return [track for track in self.tracks.values() if track.missed <= V5_TRACK_VISIBLE_MISSES]


def _safe_event_path(relative: str | None) -> Path | None:
    if not relative:
        return None
    path = (EVENTS_DIR / relative).resolve()
    if EVENTS_DIR.resolve() not in path.parents:
        return None
    return path


def _resize_for_vision(frame: Any) -> Any:
    if vision.cv2 is None:
        return frame
    height, width = frame.shape[:2]
    if width <= VISION_MAX_WIDTH:
        return frame
    scale = VISION_MAX_WIDTH / float(width)
    return vision.cv2.resize(frame, (VISION_MAX_WIDTH, int(height * scale)))


def _body_crop_and_quality(frame: Any, track: PersistentTrack) -> tuple[Any | None, float]:
    if vision.cv2 is None:
        return None, 0.0
    height, width = frame.shape[:2]
    x, y, w, h = track.bbox
    x1, y1 = max(0, x + 2), max(0, y + 2)
    x2, y2 = min(width, x + w - 2), min(height, y + h - 2)
    if x2 - x1 < 18 or y2 - y1 < 36:
        return None, 0.0
    crop = frame[y1:y2, x1:x2]
    area_ratio = ((x2 - x1) * (y2 - y1)) / max(1.0, float(width * height))
    size_quality = min(1.0, math.sqrt(max(0.0, area_ratio) / 0.16))
    touches = x <= 2 or y <= 2 or x + w >= width - 2 or y + h >= height - 2
    edge_factor = 0.68 if touches else 1.0
    confidence = max(0.0, min(1.0, float(track.confidence)))
    try:
        gray = vision.cv2.cvtColor(crop, vision.cv2.COLOR_BGR2GRAY)
        sharpness = float(vision.cv2.Laplacian(gray, vision.cv2.CV_64F).var())
        sharpness_quality = max(0.0, min(1.0, math.log1p(sharpness) / math.log(401.0)))
    except Exception:
        sharpness_quality = 0.5
    control_factor = 1.0 if track.control_valid else (0.76 if track.control_reason in {"warming", "low_confidence"} else 0.62)
    quality = (0.42 * confidence + 0.34 * size_quality + 0.24 * sharpness_quality) * edge_factor * control_factor
    return crop, max(0.05, min(1.0, quality))


def _face_quality(track: PersistentTrack, frame: Any) -> float:
    if not track.last_faces:
        return 0.0
    height, width = frame.shape[:2]
    _, _, fw, fh = max(track.last_faces, key=lambda face: face[2] * face[3])
    size = min(1.0, math.sqrt(max(1.0, fw * fh)) / max(72.0, min(width, height) * 0.18))
    return max(0.0, min(1.0, (0.65 * size + 0.35 * float(track.confidence))))


def _write_jpeg(path: Path, frame: Any, quality: int = 90) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    return bool(vision.cv2.imwrite(str(path), frame, [int(vision.cv2.IMWRITE_JPEG_QUALITY), quality]))


def _save_event_v5(self: Any, frame: Any, track: PersistentTrack, faces: list[tuple[int, int, int, int]]) -> int | None:
    ensure_schema()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = EVENTS_DIR / day / str(self.camera_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%H%M%S_%f")
    trigger_path = folder / f"track_{track.id}_{stamp}_trigger.jpg"
    best_path = folder / f"track_{track.id}_{stamp}_best.jpg"
    # Store clean frames. Recognition should not learn the rectangle/text drawn by
    # the UI/diagnostics layer as part of a person's appearance.
    if not _write_jpeg(trigger_path, frame, 90):
        return None
    if not _write_jpeg(best_path, frame, 92):
        best_path = trigger_path
    trigger_relative = str(trigger_path.relative_to(EVENTS_DIR)).replace("\\", "/")
    best_relative = str(best_path.relative_to(EVENTS_DIR)).replace("\\", "/")
    x, y, w, h = track.bbox
    now = utc_now()
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO events(
                camera_id, track_id, event_type, has_face, face_count, confidence,
                snapshot_path, trigger_snapshot_path, best_snapshot_path, bbox_json,
                created_at, last_seen_at, observation_count, identity_state,
                identity_origin, assistant_eligible, track_status, track_session
            ) VALUES (?, ?, 'person', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'collecting', 'vision', 1, 'active', ?)""",
            (
                self.camera_id, track.id, int(bool(faces)), len(faces), float(track.confidence),
                best_relative, trigger_relative, best_relative,
                json.dumps({"x": x, "y": y, "w": w, "h": h}),
                now, now, track.session_key,
            ),
        )
        conn.commit()
        event_id = int(cursor.lastrowid)
    track.trigger_snapshot_path = trigger_relative
    track.best_snapshot_path = best_relative
    return event_id


def _record_track_observation(self: Any, track: PersistentTrack, body_quality: float, face_quality: float, *, best_frame: bool, best_body: bool, best_face: bool) -> None:
    if track.event_id is None:
        return
    now_mono = time.monotonic()
    if now_mono - track.last_observation_save_monotonic < V5_OBSERVATION_INTERVAL and not (best_frame or best_body or best_face):
        return
    track.last_observation_save_monotonic = now_mono
    x, y, w, h = track.bbox
    ensure_schema()
    with connection() as conn:
        if best_frame:
            conn.execute("UPDATE track_observations SET is_best_frame = 0 WHERE event_id = ?", (track.event_id,))
        if best_body:
            conn.execute("UPDATE track_observations SET is_best_body = 0 WHERE event_id = ?", (track.event_id,))
        if best_face:
            conn.execute("UPDATE track_observations SET is_best_face = 0 WHERE event_id = ?", (track.event_id,))
        conn.execute(
            """INSERT INTO track_observations(
                event_id, camera_id, track_id, frame_seq, bbox_json, confidence,
                body_quality, face_quality, is_best_frame, is_best_body, is_best_face, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                track.event_id, self.camera_id, track.id, int(getattr(self, "live_frame_seq", 0)),
                json.dumps({"x": x, "y": y, "w": w, "h": h}), float(track.confidence),
                float(body_quality), float(face_quality), int(best_frame), int(best_body), int(best_face), utc_now(),
            ),
        )
        conn.execute(
            """DELETE FROM track_observations WHERE event_id = ? AND id NOT IN (
                SELECT id FROM track_observations WHERE event_id = ? ORDER BY id DESC LIMIT ?
            )""",
            (track.event_id, track.event_id, V5_MAX_TRACK_OBSERVATIONS),
        )
        conn.commit()


def _persist_body_observation(self: Any, track: PersistentTrack, embedding: Any, quality: float) -> None:
    if track.event_id is None:
        return
    ensure_schema()
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """INSERT INTO body_track_observations(event_id, camera_id, track_id, embedding, quality, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (track.event_id, self.camera_id, track.id, bi._vector_to_blob(embedding), float(quality), now),
        )
        conn.execute(
            """DELETE FROM body_track_observations WHERE event_id = ? AND id NOT IN (
                SELECT id FROM body_track_observations WHERE event_id = ?
                ORDER BY quality DESC, id DESC LIMIT ?
            )""",
            (track.event_id, track.event_id, V5_MAX_BODY_OBSERVATIONS),
        )
        conn.commit()


def _persist_temporal_body(self: Any, track: PersistentTrack) -> tuple[Any | None, float, int, float]:
    embedding, quality, support, stability = aggregate_temporal_body(track.body_observations)
    if track.event_id is None or embedding is None or support < 2:
        return embedding, quality, support, stability
    ensure_schema()
    now = utc_now()
    with connection() as conn:
        event = conn.execute("SELECT person_id FROM events WHERE id = ?", (track.event_id,)).fetchone()
        current = conn.execute("SELECT source, trusted, active FROM body_samples WHERE event_id = ?", (track.event_id,)).fetchone()
        person_id = event["person_id"] if event else None
        # Do not turn an automatic face identity into a trusted body anchor here.
        # Promotion happens only after face evidence and temporal stability agree.
        if current:
            source = str(current["source"] or "unlabeled")
            trusted = int(current["trusted"] or 0)
            active = int(current["active"] if current["active"] is not None else 1)
        else:
            source, trusted, active = ("unlabeled", 0, 1)
        conn.execute(
            """INSERT INTO body_samples(
                event_id, camera_id, person_id, embedding, quality, source, verified,
                created_at, updated_at, trusted, active, temporal_support, track_id, stability
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                person_id = CASE WHEN body_samples.person_id IS NOT NULL THEN body_samples.person_id ELSE excluded.person_id END,
                embedding = excluded.embedding,
                quality = excluded.quality,
                updated_at = excluded.updated_at,
                temporal_support = excluded.temporal_support,
                track_id = excluded.track_id,
                stability = excluded.stability""",
            (
                track.event_id, self.camera_id, person_id, bi._vector_to_blob(embedding), quality,
                source, int(person_id is not None), now, now, trusted, active, support, track.id, stability,
            ),
        )
        conn.commit()
    if person_id is None:
        try:
            bi.manager._score_event(track.event_id, embedding=embedding, quality=quality)
        except Exception:
            pass
    return embedding, quality, support, stability


def _promote_face_linked_body(track: PersistentTrack, aggregate: tuple[Any | None, float, int, float]) -> None:
    embedding, quality, support, stability = aggregate
    if track.event_id is None or embedding is None:
        return
    if support < V5_BODY_TRUST_MIN_SUPPORT or quality < V5_BODY_TRUST_MIN_QUALITY or stability < V5_BODY_TRUST_MIN_STABILITY:
        return
    with connection() as conn:
        row = conn.execute(
            """SELECT e.person_id, e.identity_origin,
                EXISTS(SELECT 1 FROM face_samples fs WHERE fs.event_id = e.id AND fs.person_id = e.person_id) face_agrees
            FROM events e WHERE e.id = ?""",
            (track.event_id,),
        ).fetchone()
        if row is None or row["person_id"] is None or not row["face_agrees"]:
            return
        person_id = int(row["person_id"])
        if str(row["identity_origin"] or "") == "manual":
            return
        if track.trusted_body_person_id == person_id:
            return
        conn.execute(
            """UPDATE body_samples SET person_id = ?, verified = 1, source = 'face_verified_trusted',
                trusted = 1, active = 1, temporal_support = ?, track_id = ?, stability = ?,
                quality = ?, embedding = ?, updated_at = ? WHERE event_id = ?""",
            (
                person_id, support, track.id, stability, quality,
                bi._vector_to_blob(embedding), utc_now(), track.event_id,
            ),
        )
        conn.commit()
    track.trusted_body_person_id = person_id


def _update_event_best_snapshot(self: Any, frame: Any, track: PersistentTrack, body_quality: float, face_quality: float) -> tuple[bool, bool, bool]:
    if track.event_id is None or not track.best_snapshot_path:
        return False, False, False
    frame_quality = max(0.0, min(1.0, 0.58 * body_quality + 0.42 * face_quality + (0.10 if face_quality > 0 else 0.0)))
    best_frame = frame_quality > track.best_frame_quality + 0.012
    best_body = body_quality > track.best_body_quality + 0.012
    best_face = face_quality > track.best_face_quality + 0.012
    if best_frame or (best_face and face_quality >= 0.45):
        path = _safe_event_path(track.best_snapshot_path)
        if path is not None:
            _write_jpeg(path, frame, 92)
    if best_frame:
        track.best_frame_quality = frame_quality
    if best_body:
        track.best_body_quality = body_quality
    if best_face:
        track.best_face_quality = face_quality
    return best_frame, best_body, best_face


def _event_rows_for_tracks(tracks: list[PersistentTrack]) -> dict[int, dict[str, Any]]:
    event_ids = [int(track.event_id) for track in tracks if track.event_id is not None]
    if not event_ids:
        return {}
    marks = ",".join("?" for _ in event_ids)
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT e.*, p.name person_name, pp.name probable_person_name
            FROM events e
            LEFT JOIN persons p ON p.id = e.person_id
            LEFT JOIN persons pp ON pp.id = e.probable_person_id
            WHERE e.id IN ({marks})""",
            event_ids,
        ).fetchall()
    return {int(row["id"]): dict(row) for row in rows}


def _process_temporal(self: Any, frame: Any) -> None:
    ensure_schema()
    processed = _resize_for_vision(frame)
    if not hasattr(self, "live_frame_lock"):
        self.live_frame_lock = threading.RLock()
        self.live_frame = None
        self.live_frame_seq = 0
        self.live_frame_at = 0.0
    with self.live_frame_lock:
        self.live_frame = processed.copy()
        self.live_frame_seq += 1
        self.live_frame_at = time.monotonic()

    tracks = [track for track in self.tracker.tracks.values() if isinstance(track, PersistentTrack) and track.missed <= V5_TRACK_VISIBLE_MISSES]
    active = [track for track in tracks if track.missed == 0]

    for track in active:
        if track.event_id is None:
            continue
        track.observation_count += 1
        crop, body_quality = _body_crop_and_quality(processed, track)
        face_quality = _face_quality(track, processed)
        best_frame, best_body, best_face = _update_event_best_snapshot(self, processed, track, body_quality, face_quality)
        _record_track_observation(self, track, body_quality, face_quality, best_frame=best_frame, best_body=best_body, best_face=best_face)

        now_mono = time.monotonic()
        aggregate: tuple[Any | None, float, int, float] = (None, 0.0, 0, 0.0)
        if crop is not None and body_quality >= 0.28 and now_mono - track.last_body_embed_monotonic >= V5_BODY_INTERVAL:
            track.last_body_embed_monotonic = now_mono
            try:
                embedding = bi.manager._embed_crop(crop)
                track.body_observations.append((embedding, body_quality, now_mono))
                track.body_observations = sorted(track.body_observations, key=lambda item: item[1], reverse=True)[:V5_MAX_BODY_OBSERVATIONS]
                _persist_body_observation(self, track, embedding, body_quality)
                aggregate = _persist_temporal_body(self, track)
            except Exception as exc:
                bi.manager.error = str(exc)
        elif track.body_observations:
            aggregate = aggregate_temporal_body(track.body_observations)
        _promote_face_linked_body(track, aggregate)

    rows = _event_rows_for_tracks(active)
    now = utc_now()
    with connection() as conn:
        for track in active:
            if track.event_id is None:
                continue
            row = rows.get(int(track.event_id), {})
            state = str(row.get("identity_state") or "")
            age = time.monotonic() - track.created_monotonic
            if state == "collecting" and (track.face_seen_now or age >= V5_IDENTITY_SETTLE_SECONDS):
                conn.execute("UPDATE events SET identity_state = 'pending' WHERE id = ? AND identity_state = 'collecting'", (track.event_id,))
            elif state in {"no_face", "missing_snapshot"} and track.face_seen_now:
                # A face appeared later in the same physical passage: let face ReID
                # revisit the same event instead of creating a second event.
                conn.execute("UPDATE events SET identity_state = 'pending' WHERE id = ?", (track.event_id,))
            x, y, w, h = track.bbox
            conn.execute(
                """UPDATE events SET last_seen_at = ?, observation_count = ?, confidence = ?,
                    bbox_json = ?, best_frame_quality = ?, best_face_quality = ?, best_body_quality = ?,
                    track_status = 'active' WHERE id = ?""",
                (
                    now, track.observation_count, float(track.confidence),
                    json.dumps({"x": x, "y": y, "w": w, "h": h}),
                    track.best_frame_quality, track.best_face_quality, track.best_body_quality, track.event_id,
                ),
            )
        for ended in getattr(self.tracker, "just_ended", []):
            if ended.event_id is not None:
                conn.execute(
                    "UPDATE events SET ended_at = ?, last_seen_at = COALESCE(last_seen_at, ?), track_status = 'ended' WHERE id = ?",
                    (now, now, ended.event_id),
                )
        conn.commit()

    rows = _event_rows_for_tracks(tracks)
    state_by_id = {int(item.get("track_id")): item for item in getattr(self, "tracks_state", []) if item.get("track_id") is not None}
    for track in tracks:
        item = state_by_id.get(track.id)
        if item is None:
            continue
        row = rows.get(int(track.event_id or 0), {})
        item.update({
            "event_id": track.event_id,
            "person_id": row.get("person_id"),
            "person_name": row.get("person_name"),
            "probable_person_id": row.get("probable_person_id"),
            "probable_person_name": row.get("probable_person_name"),
            "body_confidence": row.get("body_confidence"),
            "identity_state": row.get("identity_state") or "collecting",
            "observation_count": track.observation_count,
            "best_frame_quality": round(track.best_frame_quality, 3),
            "best_face_quality": round(track.best_face_quality, 3),
            "best_body_quality": round(track.best_body_quality, 3),
        })


def robust_rank_probable(query: Any, query_quality: float, gallery: list[dict[str, Any]]) -> tuple[int | None, float | None, str | None]:
    """Score identities by several trusted anchors, never by one gallery maximum."""
    per_person: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for item in gallery:
        candidate = bi._blob_to_vector(item.get("embedding"))
        if candidate is None:
            continue
        quality = max(0.0, min(1.0, float(item.get("quality") or 0.0)))
        score = bi._cosine(query, candidate) * (0.88 + 0.12 * quality)
        face_linked = str(item.get("source") or "").startswith("face_verified")
        score += bi._source_bonus(item.get("source"))
        per_person[int(item["person_id"])].append((score, face_linked))
    ranked: list[tuple[float, int, bool]] = []
    query_factor = 0.90 + 0.10 * max(0.0, min(1.0, query_quality))
    for person_id, values in per_person.items():
        top = sorted(values, key=lambda pair: pair[0], reverse=True)[:3]
        score = (sum(value for value, _ in top) / len(top)) * query_factor
        support_factor = 0.985 if len(top) == 1 else (0.995 if len(top) == 2 else 1.0)
        ranked.append((score * support_factor, person_id, any(flag for _, flag in top)))
    if not ranked:
        return None, None, None
    ranked.sort(reverse=True)
    best_score, best_person, face_linked = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else -1.0
    if best_score < BODY_REID_THRESHOLD or best_score - second_score < BODY_REID_MARGIN:
        return None, None, None
    return best_person, max(0.0, min(0.99, best_score)), "face_linked_body" if face_linked else "body_reid"


def _trusted_gallery(self: Any) -> list[dict[str, Any]]:
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT person_id, embedding, quality, source FROM body_samples
            WHERE verified = 1 AND person_id IS NOT NULL AND active = 1 AND trusted = 1
              AND source NOT IN ('false_positive', 'auto_false_positive') AND quality >= 0.38
            UNION ALL
            SELECT person_id, embedding, quality, source FROM person_body_anchors
            WHERE active = 1 AND quality >= 0.38"""
        ).fetchall()
    return [dict(row) for row in rows]


def _face_match_with_anchors(self: Any, embedding: Any) -> tuple[int | None, float | None]:
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT person_id, embedding FROM face_samples WHERE person_id IS NOT NULL
            UNION ALL
            SELECT person_id, embedding FROM person_face_anchors WHERE active = 1"""
        ).fetchall()
    best_person: int | None = None
    best_score = -1.0
    for row in rows:
        candidate = fi._blob_to_vector(row["embedding"])
        if candidate is None:
            continue
        score = fi._cosine(embedding, candidate)
        if score > best_score:
            best_score, best_person = score, int(row["person_id"])
    if best_person is not None and best_score >= fi.IDENTITY_KNOWN_THRESHOLD:
        return best_person, best_score
    return None, None


def _live_scene(self: Any, camera_id: int) -> dict[str, Any]:
    worker = self.workers.get(camera_id)
    if worker is None:
        return {"camera_id": camera_id, "live": False, "tracks": [], "count": 0}
    now = time.monotonic()
    tracks = [
        track for track in worker.tracker.tracks.values()
        if getattr(track, "missed", 99) <= 1 and now - float(getattr(track, "last_seen_monotonic", 0.0)) <= 1.25
    ]
    rows = _event_rows_for_tracks(tracks)
    out = []
    for track in tracks:
        row = rows.get(int(getattr(track, "event_id", 0) or 0), {})
        out.append({
            "track_id": int(track.id),
            "event_id": getattr(track, "event_id", None),
            "person_id": row.get("person_id"),
            "person_name": row.get("person_name"),
            "probable_person_id": row.get("probable_person_id"),
            "probable_person_name": row.get("probable_person_name"),
            "body_confidence": row.get("body_confidence"),
            "identity_state": row.get("identity_state") or "collecting",
            "has_face": bool(getattr(track, "face_seen_now", False) or getattr(track, "has_face", False)),
            "confidence": round(float(getattr(track, "confidence", 0.0)), 3),
            "bbox": {"x": track.bbox[0], "y": track.bbox[1], "w": track.bbox[2], "h": track.bbox[3]},
            "observations": int(getattr(track, "observation_count", 0)),
        })
    return {
        "camera_id": camera_id,
        "camera_name": getattr(worker, "camera_name", ""),
        "live": getattr(worker, "status", "") == "running",
        "frame_age_seconds": round(max(0.0, now - float(getattr(worker, "live_frame_at", now))), 3),
        "count": len(out),
        "tracks": out,
    }


def _latest_frame(self: Any, camera_id: int) -> tuple[Any | None, float]:
    worker = self.workers.get(camera_id)
    if worker is None or not hasattr(worker, "live_frame_lock"):
        return None, 0.0
    with worker.live_frame_lock:
        frame = None if worker.live_frame is None else worker.live_frame.copy()
        at = float(worker.live_frame_at)
    return frame, at


def _assistant_live_answer(camera_id: int, intent: str) -> Any | None:
    from . import assistant_tools as tools

    scene = vision.manager.live_scene(camera_id)
    if not scene.get("live") and not scene.get("tracks"):
        return None
    tracks = list(scene.get("tracks") or [])
    known = [(t.get("person_id"), t.get("person_name")) for t in tracks if t.get("person_id") and t.get("person_name")]
    probable = [
        (t.get("probable_person_id"), t.get("probable_person_name"))
        for t in tracks
        if not t.get("person_id") and t.get("probable_person_id") and t.get("probable_person_name")
        and float(t.get("body_confidence") or 0.0) >= BODY_REID_THRESHOLD
    ]
    unknown = max(0, len(tracks) - len(known) - len(probable))
    if intent == "count_here":
        count = len(tracks)
        return tools.CommandAnswer(f"Estou vendo {count} {'pessoa' if count == 1 else 'pessoas'} aqui agora.", intent, "live")
    if intent == "who_am_i":
        if len(tracks) != 1:
            if not tracks:
                return tools.CommandAnswer("Não estou vendo ninguém diante desta câmera agora.", intent, "unknown")
            return tools.CommandAnswer(f"Estou vendo {len(tracks)} pessoas; não consigo saber qual delas está falando comigo.", intent, "ambiguous")
        track = tracks[0]
        if track.get("person_name"):
            return tools.CommandAnswer(f"Você é {track['person_name']}.", intent, "known", int(track["person_id"]))
        if track.get("probable_person_name") and float(track.get("body_confidence") or 0.0) >= BODY_REID_THRESHOLD:
            return tools.CommandAnswer(f"Acho que você é {track['probable_person_name']}.", intent, "probable", int(track["probable_person_id"]))
        return tools.CommandAnswer("Estou vendo você, mas ainda não reconheci quem é.", intent, "unknown")
    if intent in {"who_is_here", "what_is_happening"}:
        if not tracks:
            return tools.CommandAnswer("Não estou vendo ninguém diante desta câmera agora.", intent, "live")
        parts: list[str] = []
        if known:
            parts.append(f"Estou vendo {tools._join_names([str(name) for _, name in known])}.")
        if probable:
            parts.append(f"Acho que também está aqui {tools._join_names([str(name) for _, name in probable])}.")
        if unknown:
            parts.append(f"Há também {unknown} {'pessoa que ainda não reconheci' if unknown == 1 else 'pessoas que ainda não reconheci'}.")
        return tools.CommandAnswer(" ".join(parts), intent, "live", int(known[0][0]) if known else None)
    return None


def _install_assistant_live() -> None:
    from . import assistant as assistant_module
    from . import assistant_tools as tools

    if getattr(tools, "_poi_v5_live_installed", False):
        return
    original_detect = tools.detect_intent
    original_answer = tools.answer_command

    def detect_live(text: str, person_names: list[str] | None = None) -> tuple[str, str | None]:
        q = tools.normalize_text(text)
        current_count = (
            ("quantas pessoas" in q or "quantos" in q and "pessoas" in q)
            and any(phrase in q for phrase in ("aqui", "agora", "vendo", "na camera"))
            and not any(token.startswith("pass") for token in q.split())
        )
        if current_count:
            return "count_here", None
        if any(phrase in q for phrase in ("o que esta acontecendo", "o que voce esta vendo", "o que tem aqui agora")):
            return "what_is_happening", None
        return original_detect(text, person_names)

    def answer_live(camera_id: int, text: str, timezone_name: str | None = None) -> Any:
        intent, _ = detect_live(text, tools._person_names())
        if intent in {"who_am_i", "who_is_here", "count_here", "what_is_happening"}:
            answer = _assistant_live_answer(camera_id, intent)
            if answer is not None:
                return answer
        return original_answer(camera_id, text, timezone_name)

    tools.detect_intent = detect_live
    tools.answer_command = answer_live
    tools._poi_v5_live_installed = True

    cls = assistant_module.AssistantManager
    if not getattr(cls, "_poi_v5_manual_guard", False):
        original_handle = cls._handle_event

        def handle_event(self: Any, event: dict[str, Any]) -> None:
            state = str(event.get("identity_state") or "")
            if state == "collecting":
                return
            if not bool(event.get("assistant_eligible", 1)) or str(event.get("identity_origin") or "") in {"manual", "enrollment"}:
                self._mark_event(int(event["id"]), "manual_review")
                return
            original_handle(self, event)

        cls._handle_event = handle_event
        cls._poi_v5_manual_guard = True


def _install_manual_provenance() -> None:
    cls = bi.BodyIdentityManager
    if not getattr(cls, "_poi_v5_manual_provenance", False):
        original_confirm = cls.confirm_event_identity

        def confirm(self: Any, event_id: int, person_id: int) -> None:
            original_confirm(self, event_id, person_id)
            ensure_schema()
            with connection() as conn:
                conn.execute(
                    """UPDATE body_samples SET trusted = 1, active = 1,
                        temporal_support = MAX(temporal_support, 1), updated_at = ?
                    WHERE event_id = ? AND person_id = ?""",
                    (utc_now(), event_id, person_id),
                )
                conn.execute(
                    """UPDATE events SET identity_origin = 'manual', assistant_eligible = 0,
                        identity_state = 'known', identity_confidence = 1.0 WHERE id = ?""",
                    (event_id,),
                )
                conn.commit()

        cls.confirm_event_identity = confirm
        cls._poi_v5_manual_provenance = True

    identity_cls = fi.IdentityManager
    if not getattr(identity_cls, "_poi_v5_assignment_provenance", False):
        original_cluster = identity_cls.assign_cluster

        def assign_cluster(self: Any, cluster_id: int, *, person_id: int | None = None, name: str | None = None) -> dict[str, Any]:
            ensure_schema()
            with connection() as conn:
                event_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM events WHERE unknown_cluster_id = ?", (cluster_id,)).fetchall()]
            result = original_cluster(self, cluster_id, person_id=person_id, name=name)
            resolved_person = int(result["person_id"])
            if event_ids:
                marks = ",".join("?" for _ in event_ids)
                with connection() as conn:
                    conn.execute(
                        f"UPDATE events SET identity_origin = 'manual', assistant_eligible = 0 WHERE id IN ({marks})",
                        event_ids,
                    )
                    conn.execute(
                        f"""UPDATE body_samples SET person_id = ?, verified = 1, source = 'face_verified_manual',
                            trusted = 1, active = 1, updated_at = ? WHERE event_id IN ({marks})""",
                        [resolved_person, utc_now(), *event_ids],
                    )
                    conn.commit()
            return result

        identity_cls.assign_cluster = assign_cluster
        identity_cls._poi_v5_assignment_provenance = True


def _install_identity_origin() -> None:
    cls = fi.IdentityManager
    if getattr(cls, "_poi_v5_identity_origin", False):
        return
    original_persist = cls._persist_sample

    def persist(self: Any, event: dict[str, Any], embedding: Any, crop_relative: str | None, quality: float, **kwargs: Any) -> None:
        original_persist(self, event, embedding, crop_relative, quality, **kwargs)
        ensure_schema()
        state = str(kwargs.get("identity_state") or "")
        origin = "face" if kwargs.get("person_id") is not None else ("face_unknown" if state == "unknown" else "vision")
        with connection() as conn:
            conn.execute(
                """UPDATE events SET identity_origin = CASE WHEN identity_origin = 'manual' THEN identity_origin ELSE ? END
                WHERE id = ?""",
                (origin, int(event["id"])),
            )
            conn.commit()

    cls._persist_sample = persist
    cls._poi_v5_identity_origin = True


def _install_inference_lock() -> None:
    cls = bi.BodyIdentityManager
    if getattr(cls, "_poi_v5_inference_lock", False):
        return
    original_embed = cls._embed_crop

    def embed(self: Any, crop: Any) -> Any:
        if not hasattr(self, "_poi_inference_lock"):
            self._poi_inference_lock = threading.RLock()
        with self._poi_inference_lock:
            return original_embed(self, crop)

    cls._embed_crop = embed
    cls._poi_v5_inference_lock = True


def _install_vision() -> None:
    vision.Track = PersistentTrack
    vision.CentroidTracker = PersistentCentroidTracker
    cls = vision.CameraVisionWorker
    if getattr(cls, "_poi_v5_tracking", False):
        return

    original_init = cls.__init__
    original_process = cls._process
    original_faces = cls._faces_for_track

    def worker_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.live_frame_lock = threading.RLock()
        self.live_frame = None
        self.live_frame_seq = 0
        self.live_frame_at = 0.0
        # If this worker was instantiated before Track replacement in an unusual
        # import path, force the persistent tracker explicitly.
        if not isinstance(self.tracker, PersistentCentroidTracker):
            self.tracker = PersistentCentroidTracker(VISION_PERSON_CONFIDENCE)

    def faces(self: Any, gray: Any, track: Any, width: int, height: int, face_cascade: Any) -> list[tuple[int, int, int, int]]:
        found = original_faces(self, gray, track, width, height, face_cascade)
        if isinstance(track, PersistentTrack):
            track.last_faces = list(found)
        return found

    def process(self: Any, frame: Any, detector: Any, face_cascade: Any) -> None:
        original_process(self, frame, detector, face_cascade)
        try:
            _process_temporal(self, frame)
        except Exception as exc:
            self.error = f"Temporal tracking: {exc}"

    cls.__init__ = worker_init
    cls._faces_for_track = faces
    cls._process = process
    cls._save_event = _save_event_v5
    cls._poi_v5_tracking = True

    manager_cls = vision.VisionManager
    manager_cls.live_scene = _live_scene
    manager_cls.latest_frame = _latest_frame


def _install_body_gallery() -> None:
    bi.rank_probable = robust_rank_probable
    bi.BodyIdentityManager._gallery = _trusted_gallery
    fi.IdentityManager._match_known = _face_match_with_anchors


def install() -> None:
    """Install the persistent tracking / temporal identity V5 layer additively."""
    if getattr(vision, "_poi_v5_installed", False):
        return

    original_init_db = db.init_db

    def init_db_v5() -> None:
        global _SCHEMA_READY
        original_init_db()
        _SCHEMA_READY = False
        ensure_schema()

    db.init_db = init_db_v5

    _install_inference_lock()
    _install_body_gallery()
    _install_identity_origin()
    _install_manual_provenance()
    _install_vision()
    _install_assistant_live()

    # Register the additive V5 API on the router already included by main.py.
    from .api_v34 import router as base_router
    from .v5_api import router as v5_router
    if not getattr(base_router, "_poi_v5_router", False):
        base_router.include_router(v5_router)
        base_router._poi_v5_router = True

    vision._poi_v5_installed = True

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import body_identity as bi
from . import identity as fi
from . import tracking_v5_patch as tv5
from .config import EVENTS_DIR
from .db import connection


def _safe_event_path(relative: str | None) -> Path | None:
    if not relative:
        return None
    path = (EVENTS_DIR / relative).resolve()
    root = EVENTS_DIR.resolve()
    if root not in path.parents:
        return None
    return path


def _display_relative(clean_relative: str | None, event_id: int) -> str:
    if clean_relative:
        clean = Path(clean_relative)
        name = clean.name
        if name.endswith("_best.jpg"):
            name = name[:-9] + "_display.jpg"
        elif name.endswith("_trigger.jpg"):
            name = name[:-12] + "_display.jpg"
        else:
            name = f"{clean.stem}_display{clean.suffix or '.jpg'}"
        return str(clean.with_name(name)).replace("\\", "/")
    return f"display/event_{event_id}_display.jpg"


def _clamp_box(frame: Any, bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    if frame is None or not hasattr(frame, "shape"):
        return None
    height, width = frame.shape[:2]
    x, y, w, h = [int(v) for v in bbox]
    x1 = max(0, min(width - 1, x))
    y1 = max(0, min(height - 1, y))
    x2 = max(0, min(width - 1, x + max(1, w)))
    y2 = max(0, min(height - 1, y + max(1, h)))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _annotated_frame(frame: Any, track: Any, faces: list[tuple[int, int, int, int]] | None = None) -> Any:
    annotated = frame.copy()
    cv2 = tv5.vision.cv2
    if cv2 is None:
        return annotated

    box = _clamp_box(annotated, tuple(track.bbox))
    if box is not None:
        x1, y1, x2, y2 = box
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 255, 255), 2)
        cv2.putText(
            annotated,
            f"Person #{int(track.id)}",
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
        )

    for face in faces or []:
        fbox = _clamp_box(annotated, tuple(face))
        if fbox is None:
            continue
        fx1, fy1, fx2, fy2 = fbox
        cv2.rectangle(annotated, (fx1, fy1), (fx2, fy2), (180, 180, 180), 1)
    return annotated


def _write_display(frame: Any, track: Any, event_id: int, faces: list[tuple[int, int, int, int]] | None = None) -> str | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT best_snapshot_path, trigger_snapshot_path, snapshot_path FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
    if row is None:
        return None

    clean_relative = row["best_snapshot_path"] or row["trigger_snapshot_path"] or row["snapshot_path"]
    display_relative = _display_relative(str(clean_relative) if clean_relative else None, event_id)
    display_path = _safe_event_path(display_relative)
    if display_path is None:
        return None
    display_path.parent.mkdir(parents=True, exist_ok=True)
    annotated = _annotated_frame(frame, track, faces)
    if not tv5._write_jpeg(display_path, annotated, 90):
        return None

    x, y, w, h = [int(v) for v in track.bbox]
    bbox_json = json.dumps({"x": x, "y": y, "w": w, "h": h})
    with connection() as conn:
        conn.execute(
            "UPDATE events SET snapshot_path = ?, bbox_json = ? WHERE id = ?",
            (display_relative, bbox_json, event_id),
        )
        conn.commit()
    return display_relative


def _best_clean_snapshot(event_id: int, fallback_snapshot: str | None, fallback_bbox: str | None) -> tuple[str | None, str | None]:
    with connection() as conn:
        row = conn.execute(
            "SELECT best_snapshot_path, trigger_snapshot_path, bbox_json FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        obs = conn.execute(
            """SELECT bbox_json FROM track_observations
            WHERE event_id = ? AND (is_best_frame = 1 OR is_best_face = 1)
            ORDER BY id DESC LIMIT 1""",
            (event_id,),
        ).fetchone()

    clean_candidates: list[str] = []
    if row is not None:
        for value in (row["best_snapshot_path"], row["trigger_snapshot_path"]):
            if value:
                clean_candidates.append(str(value))
    if fallback_snapshot:
        clean_candidates.append(str(fallback_snapshot))

    clean_relative: str | None = None
    for candidate in clean_candidates:
        path = _safe_event_path(candidate)
        if path is not None and path.is_file():
            clean_relative = candidate
            break

    bbox_json = str(obs["bbox_json"]) if obs is not None and obs["bbox_json"] else None
    if not bbox_json and row is not None and row["bbox_json"]:
        bbox_json = str(row["bbox_json"])
    if not bbox_json:
        bbox_json = fallback_bbox
    return clean_relative, bbox_json


def install() -> None:
    if getattr(tv5, "_poi_snapshot_display_patch", False):
        return

    original_save_event = tv5._save_event_v5
    original_update_best = tv5._update_event_best_snapshot
    original_identity_index = fi.IdentityManager._index_event
    original_body_load = bi.BodyIdentityManager._load_event_crop

    def save_event_with_display(self: Any, frame: Any, track: Any, faces: list[tuple[int, int, int, int]]) -> int | None:
        event_id = original_save_event(self, frame, track, faces)
        if event_id is not None:
            _write_display(frame, track, int(event_id), faces)
        return event_id

    def update_best_with_display(
        self: Any,
        frame: Any,
        track: Any,
        body_quality: float,
        face_quality: float,
    ) -> tuple[bool, bool, bool]:
        result = original_update_best(self, frame, track, body_quality, face_quality)
        best_frame, _best_body, best_face = result
        if track.event_id is not None and (best_frame or (best_face and face_quality >= 0.45)):
            _write_display(frame, track, int(track.event_id), list(getattr(track, "last_faces", []) or []))
        return result

    def identity_index_clean(self: Any, event: dict[str, Any]) -> Any:
        data = dict(event)
        try:
            event_id = int(data["id"])
            clean_relative, bbox_json = _best_clean_snapshot(
                event_id,
                data.get("snapshot_path"),
                data.get("bbox_json"),
            )
            if clean_relative:
                data["snapshot_path"] = clean_relative
            if bbox_json:
                data["bbox_json"] = bbox_json
        except Exception:
            pass
        return original_identity_index(self, data)

    def body_load_clean(self: Any, event: dict[str, Any]) -> Any:
        data = dict(event)
        try:
            event_id = int(data["id"])
            clean_relative, bbox_json = _best_clean_snapshot(
                event_id,
                data.get("snapshot_path"),
                data.get("bbox_json"),
            )
            if clean_relative:
                data["snapshot_path"] = clean_relative
            if bbox_json:
                data["bbox_json"] = bbox_json
        except Exception:
            pass
        return original_body_load(self, data)

    tv5._save_event_v5 = save_event_with_display
    tv5._update_event_best_snapshot = update_best_with_display
    fi.IdentityManager._index_event = identity_index_clean
    bi.BodyIdentityManager._load_event_crop = body_load_clean
    tv5._poi_snapshot_display_patch = True

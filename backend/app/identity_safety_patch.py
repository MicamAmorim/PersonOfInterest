from __future__ import annotations

import json
from typing import Any


def _parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        x = float(data.get("x", 0))
        y = float(data.get("y", 0))
        w = float(data.get("w", 0))
        h = float(data.get("h", 0))
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return x, y, w, h


def _face_center_inside(face: Any, bbox: tuple[float, float, float, float]) -> bool:
    x, y, w, h = bbox
    cx = float(face[0]) + float(face[2]) / 2.0
    cy = float(face[1]) + float(face[3]) / 2.0
    return x <= cx <= x + w and y <= cy <= y + h


def install() -> None:
    """Make automatic face association conservative in multi-person frames.

    IdentityManager historically fell back to the best face in the whole frame
    whenever no detected face center landed inside the event's person bbox. In a
    frame with two people, that could assign person B's face to person A's event.

    This patch never falls back across person boxes. If a bbox is available, a
    face must have its center inside that bbox. If there is no usable bbox, a
    face is accepted only when the frame contains exactly one face; otherwise the
    event remains without a facial identity instead of guessing.
    """
    from . import identity as fi

    cls = fi.IdentityManager
    if getattr(cls, "_poi_strict_face_bbox_patch", False):
        return

    def strict_best_face(self: Any, frame: Any, bbox_json: str | None) -> Any | None:
        height, width = frame.shape[:2]
        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(frame)
        if faces is None or len(faces) == 0:
            return None

        bbox = _parse_bbox(bbox_json)
        if bbox is not None:
            candidates = [face for face in faces if _face_center_inside(face, bbox)]
            if not candidates:
                return None
        else:
            # Without a person bbox there is no safe way to choose between two
            # people in the same frame. A single visible face is unambiguous.
            if len(faces) != 1:
                return None
            candidates = list(faces)

        return max(
            candidates,
            key=lambda f: float(f[-1]) * max(1.0, float(f[2]) * float(f[3])),
        )

    cls._poi_original_best_face = cls._best_face
    cls._best_face = strict_best_face
    cls._poi_strict_face_bbox_patch = True

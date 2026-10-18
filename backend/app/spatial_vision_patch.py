from __future__ import annotations

from typing import Any


def install() -> None:
    # Import lazily so the patch remains a narrow add-on to the existing vision
    # worker instead of introducing a dependency inside the core tracker.
    from . import vision
    from .spatial_alerts import manager as spatial_alert_manager

    cls = vision.CameraVisionWorker
    if getattr(cls, "_poi_spatial_alert_patch", False):
        return

    original_process = cls._process

    def process_with_spatial(self: Any, frame: Any, detector: Any, face_cascade: Any) -> None:
        # The established detector/tracker/event/PTZ pipeline always runs first.
        original_process(self, frame, detector, face_cascade)
        try:
            width, height = self.frame_size
            tracks = [track for track in self.tracker.tracks.values() if track.missed <= 3]
            spatial_alert_manager.process_tracks(
                int(self.camera_id),
                str(self.camera_name),
                int(width),
                int(height),
                tracks,
            )
        except Exception as exc:
            # Spatial alert failures are isolated from camera vision.
            spatial_alert_manager.error = str(exc)

    cls._process = process_with_spatial
    cls._poi_spatial_alert_patch = True

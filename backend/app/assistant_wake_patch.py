from __future__ import annotations

import threading
import time
from typing import Any

from .assistant import AssistantManager


def install() -> None:
    """Attach the local wake listener to the existing assistant lifecycle."""
    cls = AssistantManager
    if getattr(cls, "_poi_wake_lifecycle_patch", False):
        return

    original_start = cls.start
    original_stop = cls.stop

    def start_with_wake(self: Any) -> None:
        original_start(self)
        from .wake_word import manager as wake_word_manager
        wake_word_manager.start()

        def warm_persisted_listener() -> None:
            # Camera sync happens after assistant startup. Once active cameras are
            # known, preload each selected pair. WhisperModel downloads a model
            # automatically on first use when it is not present in local cache.
            for _ in range(24):
                if wake_word_manager.stop_event.is_set():
                    return
                try:
                    cameras = wake_word_manager._enabled_cameras()
                    if cameras:
                        from .assistant_command_stt_patch import _ensure_command_model

                        seen_wake: set[str] = set()
                        seen_command: set[str] = set()
                        for camera_id, camera in cameras.items():
                            wake_model = str(camera.get("wake_model") or "base")
                            command_model = str(camera.get("command_model") or "small")
                            try:
                                if wake_model not in seen_wake:
                                    wake_word_manager._ensure_model(wake_model)
                                    seen_wake.add(wake_model)
                                if command_model not in seen_command:
                                    _ensure_command_model(wake_word_manager, command_model)
                                    seen_command.add(command_model)
                            except Exception as exc:
                                wake_word_manager._set_camera_state(
                                    camera_id,
                                    model_preload_error=str(exc),
                                )
                        return
                except Exception as exc:
                    wake_word_manager.error = str(exc)
                    return
                time.sleep(0.5)

        threading.Thread(
            target=warm_persisted_listener,
            name="poi-wake-persisted-warmup",
            daemon=True,
        ).start()

    def stop_with_wake(self: Any) -> None:
        try:
            from .wake_word import manager as wake_word_manager
            wake_word_manager.stop()
        finally:
            original_stop(self)

    cls.start = start_with_wake
    cls.stop = stop_with_wake
    cls._poi_wake_lifecycle_patch = True

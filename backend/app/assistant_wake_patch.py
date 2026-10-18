from __future__ import annotations

import threading
import time
from typing import Any

from .assistant import AssistantManager


def install() -> None:
    """Attach the local wake listener to the existing assistant lifecycle.

    Import wake modules lazily inside start/stop so package initialization does
    not introduce an assistant <-> wake_word circular import.
    """
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
            # Assistant starts before startup camera sync. Give sync a short
            # window, then preload both STT models only when a saved wake
            # listener is actually active. This keeps normal installs light and
            # removes the first-question model-load delay for Tonho users.
            for _ in range(24):
                if wake_word_manager.stop_event.is_set():
                    return
                try:
                    if wake_word_manager._enabled_cameras():
                        wake_word_manager._ensure_model()
                        try:
                            from .assistant_command_stt_patch import _ensure_command_model
                            _ensure_command_model(wake_word_manager)
                        except Exception as exc:
                            # Wake detection must remain available even if the
                            # stronger model cannot be preloaded yet.
                            wake_word_manager._set_camera_state(
                                next(iter(wake_word_manager._enabled_cameras())),
                                command_model_error=str(exc),
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

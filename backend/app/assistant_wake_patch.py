from __future__ import annotations

import threading
import time
from typing import Any

from .assistant import AssistantManager


def install() -> None:
    """Attach the local wake listener to the existing assistant lifecycle.

    Import wake_word lazily inside start/stop so package initialization does not
    introduce an assistant <-> wake_word circular import.
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
            # assistant starts before startup camera sync. Give sync a short
            # window, then preload Whisper only when a saved wake listener is
            # actually active so normal users pay no model cost.
            for _ in range(24):
                if wake_word_manager.stop_event.is_set():
                    return
                try:
                    if wake_word_manager._enabled_cameras():
                        wake_word_manager._ensure_model()
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

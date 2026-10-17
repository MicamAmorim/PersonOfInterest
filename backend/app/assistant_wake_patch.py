from __future__ import annotations

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

    def stop_with_wake(self: Any) -> None:
        try:
            from .wake_word import manager as wake_word_manager
            wake_word_manager.stop()
        finally:
            original_stop(self)

    cls.start = start_with_wake
    cls.stop = stop_with_wake
    cls._poi_wake_lifecycle_patch = True

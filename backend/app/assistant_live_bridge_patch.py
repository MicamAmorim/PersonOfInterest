from __future__ import annotations


def install() -> None:
    """Refresh modules that captured answer_command before the V5 live patch.

    assistant_conversation_patch imports answer_command by value at module import
    time. V5 replaces assistant_tools.answer_command later, so this bridge points
    the already-installed conversation handler at the live-aware implementation.
    """
    from . import assistant_conversation_patch as conversation
    from . import assistant_tools

    conversation.answer_command = assistant_tools.answer_command

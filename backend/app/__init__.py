"""PersonOfInterest backend package."""

# Install narrow runtime safety/lifecycle guards before app.main imports
# singleton managers. Core model logic still lives in its own modules.
from .assistant_conversation_patch import install as _install_assistant_conversation_patch
from .assistant_v452_patch import install as _install_assistant_v452_patch
from .assistant_model_settings_patch import install as _install_assistant_model_settings_patch
from .assistant_command_stt_patch import install as _install_assistant_command_stt_patch
from .assistant_wake_patch import install as _install_assistant_wake_patch
from .body_negative_backfill import install as _install_body_negative_backfill
from .manual_learning_patch import install as _install_manual_learning_patch
from .ptz_safety_patch import install as _install_ptz_safety_patch

_install_assistant_conversation_patch()
_install_assistant_wake_patch()
_install_assistant_v452_patch()
# Model settings must wrap WakeWordManager before command STT captures its
# transcribe/model methods. This keeps per-camera model selection authoritative.
_install_assistant_model_settings_patch()
_install_assistant_command_stt_patch()
_install_body_negative_backfill()
_install_manual_learning_patch()
_install_ptz_safety_patch()

del _install_assistant_conversation_patch
del _install_assistant_v452_patch
del _install_assistant_model_settings_patch
del _install_assistant_command_stt_patch
del _install_assistant_wake_patch
del _install_body_negative_backfill
del _install_manual_learning_patch
del _install_ptz_safety_patch

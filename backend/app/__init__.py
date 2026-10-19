"""PersonOfInterest backend package."""

# Install narrow runtime safety/lifecycle guards before app.main imports
# singleton managers. Core model logic still lives in its own modules.
from .assistant_conversation_patch import install as _install_assistant_conversation_patch
from .assistant_v452_patch import install as _install_assistant_v452_patch
from .assistant_model_settings_patch import install as _install_assistant_model_settings_patch
from .assistant_command_stt_patch import install as _install_assistant_command_stt_patch
from .assistant_wake_patch import install as _install_assistant_wake_patch
from .body_negative_backfill import install as _install_body_negative_backfill
from .identity_diagnostics_patch import install as _install_identity_diagnostics_patch
from .identity_manual_guard_patch import install as _install_identity_manual_guard_patch
from .identity_safety_patch import install as _install_identity_safety_patch
from .manual_learning_patch import install as _install_manual_learning_patch
from .ptz_safety_patch import install as _install_ptz_safety_patch
from .tracking_v5_patch import install as _install_tracking_v5_patch
from .spatial_vision_patch import install as _install_spatial_vision_patch

_install_assistant_conversation_patch()
_install_assistant_wake_patch()
_install_assistant_v452_patch()
# Model settings must wrap WakeWordManager before command STT captures its
# transcribe/model methods. This keeps per-camera model selection authoritative.
_install_assistant_model_settings_patch()
_install_assistant_command_stt_patch()
_install_body_negative_backfill()
# Face identity must never borrow another person's face from a multi-person frame.
_install_identity_safety_patch()
# Reindexing face evidence must never erase a human-confirmed body-only identity.
_install_identity_manual_guard_patch()
_install_manual_learning_patch()
_install_ptz_safety_patch()
# V5 owns persistent track lifecycle, temporal body evidence, trusted galleries,
# live scene access and manual-review provenance. Spatial rules observe it after.
_install_tracking_v5_patch()
# Spatial rules only observe finished tracks; failures are isolated from vision.
_install_spatial_vision_patch()
# Diagnostics attaches a sanitized calibration ZIP endpoint to the already-used
# V3/V4 API router. It exports derived similarities, never raw embeddings/images.
_install_identity_diagnostics_patch()

del _install_assistant_conversation_patch
del _install_assistant_v452_patch
del _install_assistant_model_settings_patch
del _install_assistant_command_stt_patch
del _install_assistant_wake_patch
del _install_body_negative_backfill
del _install_identity_diagnostics_patch
del _install_identity_manual_guard_patch
del _install_identity_safety_patch
del _install_manual_learning_patch
del _install_ptz_safety_patch
del _install_tracking_v5_patch
del _install_spatial_vision_patch

"""PersonOfInterest backend package."""

# Install narrow runtime safety/lifecycle guards before app.main imports
# singleton managers. Core model logic still lives in its own modules.
from .assistant_conversation_patch import install as _install_assistant_conversation_patch
from .assistant_v452_patch import install as _install_assistant_v452_patch
from .assistant_model_settings_patch import install as _install_assistant_model_settings_patch
from .assistant_command_stt_patch import install as _install_assistant_command_stt_patch
from .assistant_wake_patch import install as _install_assistant_wake_patch
from .assistant_live_bridge_patch import install as _install_assistant_live_bridge_patch
from .assistant_web_search_patch import install as _install_assistant_web_search_patch
from .assistant_web_fallback_patch import install as _install_assistant_web_fallback_patch
from .assistant_web_speech_guard_patch import install as _install_assistant_web_speech_guard_patch
from .body_negative_backfill import install as _install_body_negative_backfill
from .body_trust_sync_patch import install as _install_body_trust_sync_patch
from .diagnostics_v5_patch import install as _install_diagnostics_v5_patch
from .event_lifecycle_patch import install as _install_event_lifecycle_patch
from .face_refinement_patch import install as _install_face_refinement_patch
from .identity_diagnostics_patch import install as _install_identity_diagnostics_patch
from .identity_manual_guard_patch import install as _install_identity_manual_guard_patch
from .identity_safety_patch import install as _install_identity_safety_patch
from .manual_integrity_v5_patch import install as _install_manual_integrity_v5_patch
from .manual_learning_patch import install as _install_manual_learning_patch
from .ptz_safety_patch import install as _install_ptz_safety_patch
from .reference_curator_patch import install as _install_reference_curator_patch
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
# Upgrade the old manual guard to recognize every manual provenance variant and
# the new identity_origin column before any reindex/worker synchronization.
_install_manual_integrity_v5_patch()
# BodyIdentity's legacy label synchronizer would otherwise collapse
# face_verified_trusted back to face_verified after each poll/restart.
_install_body_trust_sync_patch()
# User curation sits on top of automatic trust: disabled references stay disabled,
# quarantine can be manually trusted, and face/body refs can be reassigned safely.
_install_reference_curator_patch()
# Legacy Body/Push workers must not race the collecting phase of an active track.
_install_event_lifecycle_patch()
# If an initially-unknown track yields a substantially better face later, refine
# the same event to a known identity without duplicating unknown-cluster samples.
_install_face_refinement_patch()
# The conversation patch captured answer_command before V5 replaced it; refresh
# that reference so Tonho's spoken commands use the live tracker state.
_install_assistant_live_bridge_patch()
# Add local date/date+time and web research. This installs after the live bridge
# so web/date wrap the final live-aware command handler.
_install_assistant_web_search_patch()
# If SearXNG/DuckDuckGo have no useful result, try a structured Portuguese
# Wikipedia search/extract. It is free and does not require an API key.
_install_assistant_web_fallback_patch()
# Command evaluation must be side-effect free. Only the live wake-word path may
# emit the web-search preface; Tonho Lab/API calls stay silent unless they
# explicitly request playback.
_install_assistant_web_speech_guard_patch()
# Spatial rules only observe finished tracks; failures are isolated from vision.
_install_spatial_vision_patch()
# Diagnostics attaches a sanitized calibration ZIP endpoint to the already-used
# V3/V4 API router. V5 then adds trust/temporal metadata without raw embeddings.
_install_identity_diagnostics_patch()
_install_diagnostics_v5_patch()

del _install_assistant_conversation_patch
del _install_assistant_v452_patch
del _install_assistant_model_settings_patch
del _install_assistant_command_stt_patch
del _install_assistant_wake_patch
del _install_assistant_live_bridge_patch
del _install_assistant_web_search_patch
del _install_assistant_web_fallback_patch
del _install_assistant_web_speech_guard_patch
del _install_body_negative_backfill
del _install_body_trust_sync_patch
del _install_diagnostics_v5_patch
del _install_event_lifecycle_patch
del _install_face_refinement_patch
del _install_identity_diagnostics_patch
del _install_identity_manual_guard_patch
del _install_identity_safety_patch
del _install_manual_integrity_v5_patch
del _install_manual_learning_patch
del _install_ptz_safety_patch
del _install_reference_curator_patch
del _install_tracking_v5_patch
del _install_spatial_vision_patch

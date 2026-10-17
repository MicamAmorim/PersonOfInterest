"""PersonOfInterest backend package."""

# Install narrow runtime safety/learning guards before app.main imports singleton
# managers. Core OSNet support itself lives in body_identity.py.
from .body_negative_backfill import install as _install_body_negative_backfill
from .manual_learning_patch import install as _install_manual_learning_patch
from .ptz_safety_patch import install as _install_ptz_safety_patch

_install_body_negative_backfill()
_install_manual_learning_patch()
_install_ptz_safety_patch()

del _install_body_negative_backfill
del _install_manual_learning_patch
del _install_ptz_safety_patch

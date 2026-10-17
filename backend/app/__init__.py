"""PersonOfInterest backend package."""

# Install narrow runtime safety guards before app.main imports singleton managers.
# Core OSNet support itself lives in body_identity.py; this hook only bounds the
# one-time migration/backfill of historical false-positive reviews.
from .body_negative_backfill import install as _install_body_negative_backfill
from .ptz_safety_patch import install as _install_ptz_safety_patch

_install_body_negative_backfill()
_install_ptz_safety_patch()

del _install_body_negative_backfill
del _install_ptz_safety_patch

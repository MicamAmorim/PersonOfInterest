"""PersonOfInterest backend package."""

# Install runtime compatibility/safety patches before app.main imports the
# singleton managers.
from .body_reid_patch import install as _install_body_reid_patch
from .ptz_safety_patch import install as _install_ptz_safety_patch

_install_body_reid_patch()
_install_ptz_safety_patch()

del _install_body_reid_patch
del _install_ptz_safety_patch

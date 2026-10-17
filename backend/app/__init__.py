"""PersonOfInterest backend package."""

# Keep ONVIF service discovery pinned to the camera host before app.main imports
# the singleton managers. Body ReID compatibility now lives in body_identity.py
# itself and no longer needs a runtime monkey-patch.
from .ptz_safety_patch import install as _install_ptz_safety_patch

_install_ptz_safety_patch()

del _install_ptz_safety_patch

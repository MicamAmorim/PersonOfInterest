"""PersonOfInterest backend package."""

# Install small runtime compatibility patches before app.main imports the
# singleton managers. This keeps user-facing review robust across ONNX exports
# with fixed batch dimensions.
from .body_reid_patch import install as _install_body_reid_patch

_install_body_reid_patch()

del _install_body_reid_patch

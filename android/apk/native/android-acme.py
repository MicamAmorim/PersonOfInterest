import json
from pathlib import Path
import shutil
import sys


module = Path(json.load(sys.stdin)["Dir"])
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
patched = output / "tailscale"
if not patched.exists():
    shutil.copytree(module, patched)
for name, original, updated in (
    ("cert.go", "!ios && !android && !js && !ts_omit_acme", "!ios && !js && !ts_omit_acme"),
    ("disabled_stubs.go", "ios || android || js", "ios || js"),
):
    relative = Path("ipn", "localapi", name)
    source = module / relative
    text = source.read_text(encoding="utf-8")
    marker = f"//go:build {original}\n"
    if text.count(marker) != 1:
        raise SystemExit(f"Tailscale build tags changed in {name}")
    destination = patched / relative
    destination.chmod(0o644)
    destination.write_text(text.replace(marker, f"//go:build {updated}\n"), encoding="utf-8")

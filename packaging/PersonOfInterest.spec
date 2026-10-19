# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path.cwd().resolve()
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"
PACKAGING = ROOT / "packaging"

if not FRONTEND.is_dir() or not BACKEND.is_dir():
    raise SystemExit("Execute PyInstaller a partir da raiz do repositório PersonOfInterest.")

GO2RTC = ROOT / "bin" / ("go2rtc.exe" if os.name == "nt" else "go2rtc")
if not GO2RTC.is_file():
    raise SystemExit(f"go2rtc não encontrado para este build: {GO2RTC}")


datas = [(str(FRONTEND), "frontend")]
binaries = [(str(GO2RTC), "bin")]
hiddenimports = collect_submodules("uvicorn")

# These packages contain dynamic modules/native libraries that PyInstaller may
# not discover from static imports alone. collect_all is intentionally best-
# effort so future dependency changes do not make the spec brittle.
for package in (
    "av",
    "certifi",
    "cryptography",
    "ctranslate2",
    "edge_tts",
    "faster_whisper",
    "onnxruntime",
    "pywebpush",
    "tzdata",
    "websockets",
):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hidden
    except Exception:
        pass

if os.getenv("POI_BUNDLE_MODELS", "0") == "1":
    model_dir = ROOT / "data" / "models"
    required = (
        "yolox_tiny.onnx",
        "face_detection_yunet_2023mar.onnx",
        "face_recognition_sface_2021dec.onnx",
        "osnet_x0_25_msmt17.onnx",
    )
    missing = [name for name in required if not (model_dir / name).is_file()]
    if missing:
        raise SystemExit("-BundleModels solicitado, mas faltam: " + ", ".join(missing))
    datas.append((str(model_dir), "models"))


a = Analysis(
    [str(PACKAGING / "launcher.py")],
    pathex=[str(ROOT), str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PersonOfInterest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PersonOfInterest",
)

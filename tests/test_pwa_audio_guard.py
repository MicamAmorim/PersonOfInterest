from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_manifest_has_installable_shape() -> None:
    manifest = json.loads((FRONTEND / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "PersonOfInterest"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    sizes = {icon.get("sizes") for icon in manifest.get("icons", [])}
    assert "192x192" in sizes
    assert "512x512" in sizes


def test_pwa_assets_are_loaded_directly() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert '/v54-pwa.css' in html
    assert '/v54-pwa.js' in html


def test_viewer_does_not_delegate_microphone_by_default() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    viewer_line = next(line for line in html.splitlines() if 'id="viewerFrame"' in line)
    assert 'microphone' not in viewer_line


def test_ptt_has_explicit_microphone_cleanup() -> None:
    ptt = (FRONTEND / "v4-audio-fix.js").read_text(encoding="utf-8")
    player = (FRONTEND / "camera-webrtc.html").read_text(encoding="utf-8")
    assert "setViewerMicrophonePermission(true)" in ptt
    assert "setViewerMicrophonePermission(false)" in ptt
    assert "stop-talkback" in ptt
    assert "stop-talkback" in player
    assert "track.stop()" in player
    assert "pc?.close()" in player


def test_service_worker_caches_new_assets() -> None:
    sw = (FRONTEND / "sw.js").read_text(encoding="utf-8")
    assert "personofinterest-v5.4-pwa-audio-guard" in sw
    assert "/v54-pwa.css" in sw
    assert "/v54-pwa.js" in sw

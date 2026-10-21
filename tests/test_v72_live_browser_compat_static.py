from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_live_patch_routes_cards_through_camera_webrtc():
    text = (ROOT / "frontend/v72-live-browser-compat.js").read_text(encoding="utf-8")
    assert "camera-webrtc.html" in text
    assert ".camera-card[data-id]" in text
    assert "poiBrowserCameraUrl" in text


def test_camera_webrtc_uses_dedicated_browser_stream():
    text = (ROOT / "frontend/camera-webrtc.html").read_text(encoding="utf-8")
    assert "_browser" in text
    assert "Carregando vídeo H.264" in text


def test_asset_loader_loads_live_browser_compat_after_legacy_layers():
    text = (ROOT / "frontend/v49-identity-diagnostics.js").read_text(encoding="utf-8")
    assert "v72-live-browser-compat.js" in text
    assert "data-poi-v72-live" in text

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_browser_media_route_disables_stale_browser_cache():
    text = (ROOT / "backend/app/browser_media_route_patch.py").read_text(encoding="utf-8")
    assert '"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"' in text
    assert '"Pragma": "no-cache"' in text
    assert '"Expires": "0"' in text


def test_live_view_uses_dedicated_browser_stream_and_cache_buster():
    text = (ROOT / "frontend/camera-webrtc.html").read_text(encoding="utf-8")
    assert "`${camera.stream_name}_browser`" in text
    assert "v=v7.2.1" in text


def test_pwa_cache_is_bumped_for_browser_media_fix():
    text = (ROOT / "frontend/sw.js").read_text(encoding="utf-8")
    assert "personofinterest-v7.2.1-browser-media-cache-live-fix" in text

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_browser_recording_response_disables_stale_codec_cache():
    text = (ROOT / "backend/app/browser_media_route_patch.py").read_text(encoding="utf-8")
    assert '"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"' in text
    assert '"Pragma": "no-cache"' in text
    assert '"Expires": "0"' in text

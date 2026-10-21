from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_timeline_urls_are_versioned_from_recording_file_metadata():
    text = (ROOT / "backend/app/timeline_player_api.py").read_text(encoding="utf-8")
    assert "media_version" in text
    assert "?v=" in text


def test_browser_media_route_disables_stale_browser_cache():
    text = (ROOT / "backend/app/browser_media_route_patch.py").read_text(encoding="utf-8")
    assert '"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"' in text
    assert '"Pragma": "no-cache"' in text
    assert '"Expires": "0"' in text

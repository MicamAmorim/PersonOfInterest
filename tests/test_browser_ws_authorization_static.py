from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_browser_ws_authorization_is_limited_to_camera_derivative():
    text = (ROOT / "backend/app/browser_ws_authorization_patch.py").read_text(encoding="utf-8")
    assert 'browser_suffix = "_browser"' in text
    assert 'SELECT stream_name FROM cameras WHERE stream_name = ? AND enabled = 1' in text
    assert 'allowed = {str(row["stream_name"]), f"{row[\'stream_name\']}{browser_suffix}"}' in text
    assert 'await api_v34._bridge_websocket' in text


def test_browser_ws_patch_is_installed_before_app_startup():
    text = (ROOT / "backend/app/timeline_analysis_patch.py").read_text(encoding="utf-8")
    assert "install_browser_ws_authorization_patch()" in text

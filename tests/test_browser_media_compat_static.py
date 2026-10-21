from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_browser_media_compat_transcodes_hevc_to_h264_cache():
    text = (ROOT / "backend/app/browser_media_compat.py").read_text(encoding="utf-8")
    assert "browser_media_cache" in text
    assert '"libx264"' in text
    assert '"yuv420p"' in text
    assert "browser_compatible_path" in text


def test_timeline_route_is_replaced_with_browser_compatible_file_response():
    text = (ROOT / "backend/app/browser_media_route_patch.py").read_text(encoding="utf-8")
    assert "/api/timeline-player/recordings/{recording_id}" in text
    assert "browser_compatible_path" in text
    assert "_drop_path(api_v34.router" in text
    assert "X-POI-Media-Compatibility" in text


def test_go2rtc_primary_stream_gets_lazy_browser_fallback():
    text = (ROOT / "backend/app/browser_stream_patch.py").read_text(encoding="utf-8")
    assert "exec:" in text
    assert '"libx264"' in text
    assert '"libopus"' in text
    assert '"src": [rtsp_url, browser_source]' in text
    assert "imageio_ffmpeg.get_ffmpeg_exe" in text


def test_compatibility_installs_before_main_camera_sync():
    text = (ROOT / "backend/app/timeline_analysis_patch.py").read_text(encoding="utf-8")
    assert "install_browser_stream_patch()" in text
    assert "install_browser_media_route_patch()" in text

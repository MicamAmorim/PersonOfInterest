from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_browser_media_compat_transcodes_hevc_to_h264_cache():
    text = (ROOT / "backend/app/browser_media_compat.py").read_text(encoding="utf-8")
    assert "browser_media_cache" in text
    assert '"libx264"' in text
    assert '"yuv420p"' in text
    assert "browser_compatible_path" in text


def test_timeline_player_uses_browser_compatible_path():
    text = (ROOT / "backend/app/timeline_player_api.py").read_text(encoding="utf-8")
    assert "browser_compatible_path" in text


def test_go2rtc_has_browser_h264_stream():
    text = (ROOT / "backend/app/go2rtc.py").read_text(encoding="utf-8")
    assert "browser_stream_name" in text
    assert "#video=h264" in text


def test_start_configures_go2rtc_ffmpeg_binary():
    text = (ROOT / "start.ps1").read_text(encoding="utf-8")
    assert "imageio_ffmpeg.get_ffmpeg_exe" in text
    assert "ffmpeg:" in text
    assert "bin:" in text

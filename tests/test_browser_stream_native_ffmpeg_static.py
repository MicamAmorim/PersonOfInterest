from pathlib import Path


def test_browser_stream_uses_native_go2rtc_ffmpeg_source():
    text = Path('backend/app/browser_stream_patch.py').read_text(encoding='utf-8')
    assert 'ffmpeg:{stream_name}#video=h264#audio=opus' in text
    assert 'exec:' not in text


def test_start_configures_go2rtc_ffmpeg_binary():
    text = Path('start.ps1').read_text(encoding='utf-8')
    assert 'imageio_ffmpeg.get_ffmpeg_exe()' in text
    assert 'ffmpeg:' in text
    assert 'bin:' in text

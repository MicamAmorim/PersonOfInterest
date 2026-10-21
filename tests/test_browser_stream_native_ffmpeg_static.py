from pathlib import Path


def test_browser_stream_uses_explicit_local_rtsp_ffmpeg_source():
    text = Path('backend/app/browser_stream_patch.py').read_text(encoding='utf-8')
    assert 'local_restream_url(stream_name)' in text
    assert '#video=h264#audio=copy' in text
    assert '#audio=opus' not in text
    assert 'exec:' not in text


def test_start_configures_go2rtc_ffmpeg_binary():
    text = Path('start.ps1').read_text(encoding='utf-8')
    assert 'imageio_ffmpeg.get_ffmpeg_exe()' in text
    assert 'ffmpeg:' in text
    assert 'bin:' in text

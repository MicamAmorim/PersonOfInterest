from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def read(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_v56_assets_are_loaded_directly_and_cached():
    index = read("index.html")
    sw = read("sw.js")
    assert '/v56-viewer-ux.css' in index
    assert '/v56-viewer-ux.js' in index
    assert '/v56-viewer-ux.css' in sw
    assert '/v56-viewer-ux.js' in sw


def test_viewer_fullscreen_is_additive_and_attempts_landscape_lock():
    script = read("v56-viewer-ux.js")
    assert "dialog.requestFullscreen" in script
    assert "screen.orientation.lock('landscape')" in script
    assert "poi-faux-fullscreen" in script
    assert "document.exitFullscreen" in script


def test_mobile_ptt_reuses_existing_safe_button():
    script = read("v56-viewer-ux.js")
    audio_guard = read("v4-audio-fix.js")
    assert "getElementById('talkMicBtn')" in script
    assert "dock.appendChild(talk)" in script
    assert "talk.cloneNode" not in script
    assert "talk.addEventListener('pointerdown', startTalk" in audio_guard
    assert "stopOutgoingTalkback()" in audio_guard


def test_fullscreen_styles_preserve_viewer_controls():
    css = read("v56-viewer-ux.css")
    for token in (
        ".viewer-actions",
        ".viewer-mobile-talk-dock",
        ".ptz-joystick",
        ".viewer-footer-status",
        ".vision-status",
    ):
        assert token in css

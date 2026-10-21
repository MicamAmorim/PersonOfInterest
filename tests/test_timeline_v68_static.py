from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v68_tonho_is_first_class_hybrid_media() -> None:
    js = (ROOT / "frontend" / "v68-audio-playback-bridge.js").read_text(encoding="utf-8")
    assert "nextAudio" in js
    assert "previousAudio" in js
    assert "#poiHybridNext" in js
    assert "#poiHybridPrev" in js
    assert "focusAudio" in js
    assert "pauseHybrid" in js


def test_v68_audio_click_pauses_visual_autoadvance_first() -> None:
    js = (ROOT / "frontend" / "v68-audio-playback-bridge.js").read_text(encoding="utf-8")
    assert "#poiV66AudioTrack [data-audio-id]" in js
    assert "pauseHybrid();" in js
    assert "clearVisualSelectionForAudio();" in js
    assert "event.stopImmediatePropagation();" in js


def test_v68_bridges_clip_end_to_tonho_before_next_visual() -> None:
    js = (ROOT / "frontend" / "v68-audio-playback-bridge.js").read_text(encoding="utf-8")
    assert "bindVideoEndBridge" in js
    assert "video.addEventListener('ended'" in js
    assert "Beat V6.2's delayed advanceAfter" in js

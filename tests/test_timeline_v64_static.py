from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v64_space_handler_runs_in_capture_phase():
    js = text("frontend/v64-playback-picker-fixes.js")
    assert "event.code !== 'Space'" in js
    assert "event.preventDefault()" in js
    assert "event.stopImmediatePropagation()" in js
    assert "}, true);" in js
    assert "toggleHybridPlayback()" in js


def test_v64_direct_clip_reuses_thumb_playback_path():
    js = text("frontend/v64-playback-picker-fixes.js")
    assert "#poiV63ClipTrack [data-v63-clip]" in js
    assert "#poiEventStrip [data-event-card=" in js
    assert "card.click()" in js


def test_v64_person_picker_has_direct_no_cache_api_fallback():
    js = text("frontend/v64-playback-picker-fixes.js")
    assert "/api/persons?_=" in js
    assert "cache: 'no-store'" in js
    assert "credentials: 'same-origin'" in js
    assert "Selecione uma pessoa" in js
    assert "＋ Novo nome" in js


def test_v64_video_is_never_cover_cropped():
    css = text("frontend/v64-playback-picker-fixes.css")
    assert "aspect-ratio:16/9!important" in css
    assert "object-fit:contain!important" in css
    assert "object-position:center center!important" in css


def test_v64_is_loaded_and_cached():
    loader = text("frontend/v49-identity-diagnostics.js")
    sw = text("frontend/sw.js")
    assert "/v64-playback-picker-fixes.css" in loader
    assert "/v64-playback-picker-fixes.js" in loader
    assert "/v64-playback-picker-fixes.css" in sw
    assert "/v64-playback-picker-fixes.js" in sw
    assert "personofinterest-v6.4-playback-picker-fixes" in sw

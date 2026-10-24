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


def test_v61_owns_person_picker_and_fetches_people_directly():
    js = text("frontend/v61-timeline-interactions.js")
    assert 'id="poiClassifyPersonPicker"' in js
    assert "/api/persons?_=" in js
    assert "cache: 'no-store'" in js
    assert "AbortController" in js
    assert "Selecione uma pessoa" in js
    assert "＋ Novo nome" in js
    assert "/api/identity/events/${id}/assign" in js


def test_v64_no_longer_owns_person_picker():
    js = text("frontend/v64-playback-picker-fixes.js")
    assert "/api/persons?_=" not in js
    assert "startPersonPickerRecovery" not in js
    assert "bindPersonPickerDirect" not in js


def test_v64_video_is_never_cover_cropped():
    css = text("frontend/v64-playback-picker-fixes.css")
    assert "aspect-ratio:16/9!important" in css
    assert "object-fit:contain!important" in css
    assert "object-position:center center!important" in css


def test_v64_has_no_recursive_stage_mutation_observer():
    js = text("frontend/v64-playback-picker-fixes.js")
    assert "new MutationObserver(hardenVideoFit)" not in js
    assert "observe(stage" not in js


def test_v65_hotfix_is_not_loaded_anymore():
    loader = text("frontend/v49-identity-diagnostics.js")
    sw = text("frontend/sw.js")
    assert "/v65-person-picker-hotfix.js" not in loader
    assert "/v65-person-picker-hotfix.js" not in sw


def test_v64_is_loaded_and_cached():
    loader = text("frontend/v49-identity-diagnostics.js")
    sw = text("frontend/sw.js")
    assert "/v64-playback-picker-fixes.css" in loader
    assert "/v64-playback-picker-fixes.js" in loader
    assert "/v64-playback-picker-fixes.css" in sw
    assert "/v64-playback-picker-fixes.js" in sw
    assert "personofinterest-v6.5.1-picker-root-fix" in sw

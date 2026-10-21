from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v66_analysis_api_is_read_only_and_exposes_bbox_and_audio_sessions():
    py = text("backend/app/timeline_analysis_api.py")
    assert '@router.get("/api/timeline-player/analysis")' in py
    assert "e.bbox_json" in py
    assert '"bbox": _bbox(row["bbox_json"])' in py
    assert "assistant_wake_log" in py
    assert "matches_wake_phrase(transcript)" in py
    assert '"audio_sessions": sessions' in py
    assert "INSERT INTO" not in py
    assert "UPDATE events" not in py
    assert "DELETE FROM" not in py


def test_v66_audio_sessions_only_start_from_actual_wake_phrase():
    py = text("backend/app/timeline_analysis_api.py")
    assert "wake_start = matches_wake_phrase(transcript)" in py
    assert "if wake_start:" in py
    assert '"turns": []' in py
    assert '"user": transcript' in py
    assert '"tonho": response' in py


def test_v66_keeps_clip_and_event_as_separate_timeline_concepts():
    js = text("frontend/v66-event-overlay-audio-track.js")
    assert "renderClipEventPoints" in js
    assert "item.has_clip" in js
    assert "poi-v66-event-with-clip" in js
    assert "#poiV63ClipTrack [data-event-id]" in js
    assert "#poiV63EventTrack [data-event-id]" in js


def test_v66_has_dynamic_bbox_and_tonho_track():
    js = text("frontend/v66-event-overlay-audio-track.js")
    css = text("frontend/v66-event-overlay-audio-track.css")
    assert "poiV66BBox" in js
    assert "showBBox" in js
    assert "poiV66AudioTrack" in js
    assert "audio_sessions" in js
    assert "showAudioOverlay" in js
    assert "Você" in js
    assert "Tonho" in js
    assert ".poi-v66-bbox" in css
    assert ".poi-v66-track-audio" in css
    assert "@media(max-width:760px)" in css


def test_v66_uses_existing_pause_events_for_visual_and_tonho_events():
    js = text("frontend/v66-event-overlay-audio-track.js")
    assert "poiV63PauseEvents" in js
    assert "crossedVisual" in js
    assert "crossedAudio" in js
    assert "video.pause()" in js


def test_v66_observer_is_childlist_only_not_attribute_recursive():
    js = text("frontend/v66-event-overlay-audio-track.js")
    assert "new MutationObserver" in js
    assert "observe(track, { childList: true })" in js
    assert "attributes: true" not in js


def test_v66_assets_are_loaded_and_cached():
    loader = text("frontend/v49-identity-diagnostics.js")
    sw = text("frontend/sw.js")
    for asset in ("/v66-event-overlay-audio-track.css", "/v66-event-overlay-audio-track.js"):
        assert asset in loader
        assert asset in sw
    assert "personofinterest-v6.6-event-overlay-tonho-track" in sw


def test_v66_backend_patch_is_installed_without_touching_vision_core():
    package = text("backend/app/__init__.py")
    patch = text("backend/app/timeline_analysis_patch.py")
    assert "_install_timeline_analysis_patch()" in package
    assert "timeline_analysis_router" in patch
    assert "api_v34.router.include_router" in patch

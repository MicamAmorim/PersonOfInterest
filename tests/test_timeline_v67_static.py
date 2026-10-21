from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v67_audio_only_layout_assets_are_loaded() -> None:
    loader = (ROOT / "frontend" / "v49-identity-diagnostics.js").read_text(encoding="utf-8")
    sw = (ROOT / "frontend" / "sw.js").read_text(encoding="utf-8")
    assert "/v67-timeline-overlay-layout.css" in loader
    assert "/v67-timeline-overlay-layout.js" in loader
    assert "/v67-timeline-overlay-layout.css" in sw
    assert "/v67-timeline-overlay-layout.js" in sw


def test_audio_only_hides_empty_state_and_stage_classify_button() -> None:
    css = (ROOT / "frontend" / "v67-timeline-overlay-layout.css").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "v67-timeline-overlay-layout.js").read_text(encoding="utf-8")
    assert "#poiTimelineClassify{display:none!important}" in css
    assert "poi-v67-audio-only #poiTimelineEmpty" in css
    assert "Conversa com Tonho" in js
    assert "clearStaleVisualSelection" in js


def test_v67_observer_cannot_recurse_on_styles() -> None:
    js = (ROOT / "frontend" / "v67-timeline-overlay-layout.js").read_text(encoding="utf-8")
    assert "attributeFilter: ['hidden']" in js
    assert "attributeFilter: ['style']" not in js


def test_timeline_analysis_prefers_trigger_time_bbox() -> None:
    api = (ROOT / "backend" / "app" / "timeline_analysis_api.py").read_text(encoding="utf-8")
    assert "track_observations" in api
    assert "trigger_bbox_json" in api
    assert "ORDER BY t.created_at ASC, t.id ASC" in api
    assert "julianday(t.created_at)" not in api
    assert '"bbox": trigger_bbox or display_bbox' in api

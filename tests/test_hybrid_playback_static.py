from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def read(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_hybrid_player_has_classic_controls_and_spacebar():
    js = read("v62-hybrid-playback.js")
    for token in (
        "poiHybridPrev",
        "poiHybridBack",
        "poiHybridPlay",
        "poiHybridForward",
        "poiHybridNext",
        "event.code !== 'Space'",
        "togglePlayback()",
    ):
        assert token in js


def test_hybrid_player_sequences_snapshots_and_video():
    js = read("v62-hybrid-playback.js")
    assert "type: 'snapshot'" in js
    assert "type: 'video'" in js
    assert "scheduleSnapshotAdvance" in js
    assert "waitAndPlayVideo" in js
    assert "advanceAfter" in js
    assert "recordingAt" in js
    assert "nextMedia" in js


def test_clicking_event_starts_playback_and_syncs_selection():
    js = read("v62-hybrid-playback.js")
    assert "#poiEventMarkers [data-event-id]" in js
    assert "#poiEventStrip [data-event-card]" in js
    assert "syncSelectedEvent" in js
    assert "setPlaying(true)" in js
    assert "playFromNeedle()" in js


def test_classification_uses_existing_person_or_new_name():
    js = read("v62-hybrid-playback.js")
    assert "poiClassifyPersonSelect" in js
    assert "＋ Novo nome…" in js
    assert "payload.person_id" in js
    assert "payload.name" in js
    assert "/api/identity/events/${eventId}/assign" in js


def test_v62_assets_are_loaded_and_cached():
    loader = read("v49-identity-diagnostics.js")
    sw = read("sw.js")
    assert "/v62-hybrid-playback.js" in loader
    assert "/v62-hybrid-playback.css" in loader
    assert "data-poi-v62" in loader
    assert "personofinterest-v6.2-hybrid-playback" in sw
    assert "/v62-hybrid-playback.js" in sw
    assert "/v62-hybrid-playback.css" in sw

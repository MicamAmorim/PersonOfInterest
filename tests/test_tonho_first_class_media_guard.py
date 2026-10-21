from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v69_is_loaded_by_frontend_loader() -> None:
    loader = (ROOT / "frontend" / "v49-identity-diagnostics.js").read_text(encoding="utf-8")
    assert "/v69-tonho-media-navigation.js" in loader
    assert "data-poi-v69" in loader


def test_v69_owns_all_navigation_controls_before_legacy_handlers() -> None:
    script = (ROOT / "frontend" / "v69-tonho-media-navigation.js").read_text(encoding="utf-8")
    assert "window.addEventListener('click'" in script
    for selector in ("#poiHybridNext", "#poiHybridPrev", "#poiHybridForward", "#poiHybridBack"):
        assert selector in script
    assert "event.stopImmediatePropagation()" in script
    assert "function jumpTemporal(direction)" in script
    assert "function seekRelativeOwned(delta)" in script
    assert "navToken" in script


def test_tonho_focus_does_not_depend_on_synthetic_track_click() -> None:
    script = (ROOT / "frontend" / "v69-tonho-media-navigation.js").read_text(encoding="utf-8")
    assert "function renderAudioOverlay(session)" in script
    assert "overlay.hidden = false" in script
    assert "button.click()" not in script
    assert "requestAnimationFrame(() => renderAudioOverlay(session))" in script


def test_v69_merges_visual_and_tonho_media_chronologically() -> None:
    script = (ROOT / "frontend" / "v69-tonho-media-navigation.js").read_text(encoding="utf-8")
    assert "function temporalItems()" in script
    assert "type: 'audio'" in script
    assert "function nextTemporal(second)" in script
    assert "function previousTemporal(second)" in script
    assert "const threshold = Number(second) - .35" in script
    assert "activeVisual" not in script
    assert "function visualAt(second)" in script
    assert "function audioAt(second)" in script


def test_service_worker_caches_v69_navigation_revision() -> None:
    sw = (ROOT / "frontend" / "sw.js").read_text(encoding="utf-8")
    assert "personofinterest-v6.9.2-chronological-navigation" in sw
    assert "'/v69-tonho-media-navigation.js'" in sw

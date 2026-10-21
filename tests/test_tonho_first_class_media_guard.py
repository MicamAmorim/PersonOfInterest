from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v69_is_loaded_by_frontend_loader() -> None:
    loader = (ROOT / "frontend" / "v49-identity-diagnostics.js").read_text(encoding="utf-8")
    assert "/v69-tonho-media-navigation.js" in loader
    assert "data-poi-v69" in loader


def test_v69_owns_navigation_before_v68_document_capture() -> None:
    script = (ROOT / "frontend" / "v69-tonho-media-navigation.js").read_text(encoding="utf-8")
    assert "window.addEventListener('click'" in script
    assert "#poiHybridNext" in script
    assert "#poiHybridPrev" in script
    assert "event.stopImmediatePropagation()" in script


def test_tonho_focus_does_not_depend_on_synthetic_track_click() -> None:
    script = (ROOT / "frontend" / "v69-tonho-media-navigation.js").read_text(encoding="utf-8")
    assert "function renderAudioOverlay(session)" in script
    assert "overlay.hidden = false" in script
    assert "button.click()" not in script
    assert "requestAnimationFrame(() => renderAudioOverlay(session))" in script


def test_service_worker_caches_v69() -> None:
    sw = (ROOT / "frontend" / "sw.js").read_text(encoding="utf-8")
    assert "personofinterest-v6.9-tonho-first-class-media" in sw
    assert "'/v69-tonho-media-navigation.js'" in sw

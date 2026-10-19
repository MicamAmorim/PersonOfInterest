from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend" / "app"


def test_v55_assets_are_loaded_directly():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert "/v55-mobile-dashboard.css" in html
    assert "/v55-mobile-dashboard.js" in html


def test_mobile_navigation_keeps_all_primary_paths():
    js = (FRONTEND / "v55-mobile-dashboard.js").read_text(encoding="utf-8")
    for view in ("dashboard", "cameras", "timeline", "identity", "more"):
        assert f"['{view}'" in js or f"'{view}'" in js
    for secondary in ("analytics", "alerts", "settings"):
        assert f'data-more-view="{secondary}"' in js


def test_analytics_patch_is_read_only():
    code = (BACKEND / "analytics_v55_patch.py").read_text(encoding="utf-8")
    assert '"/api/analytics/overview"' in code
    upper = code.upper()
    assert "INSERT INTO" not in upper
    assert "UPDATE EVENTS" not in upper
    assert "DELETE FROM" not in upper
    assert "DROP TABLE" not in upper


def test_mobile_viewer_does_not_change_vision_engine_assets():
    js = (FRONTEND / "v55-mobile-dashboard.js").read_text(encoding="utf-8")
    assert "tracking_v5" not in js
    assert "BODY_REID" not in js
    assert "FACE_REID" not in js


def test_service_worker_caches_v55_assets():
    sw = (FRONTEND / "sw.js").read_text(encoding="utf-8")
    assert "personofinterest-v5.5-mobile-dashboard" in sw
    assert "/v55-mobile-dashboard.css" in sw
    assert "/v55-mobile-dashboard.js" in sw

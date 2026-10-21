from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" / "app" / "session_diagnostics_api.py"
PATCH = ROOT / "backend" / "app" / "session_diagnostics_patch.py"
FRONTEND = ROOT / "frontend" / "v70-full-diagnostics.js"
LOADER = ROOT / "frontend" / "v49-identity-diagnostics.js"
SW = ROOT / "frontend" / "sw.js"


def test_backend_exposes_session_lifecycle_and_zip() -> None:
    text = BACKEND.read_text(encoding="utf-8")
    for needle in (
        'prefix="/api/diagnostics/session"',
        '@router.post("/start")',
        '@router.post("/{session_id}/events")',
        '@router.post("/{session_id}/sample")',
        '@router.post("/{session_id}/marker")',
        '@router.post("/{session_id}/screen")',
        '@router.post("/{session_id}/stop")',
        '@router.get("/{session_id}/export")',
        'diagnostic-report.html',
        'db-summary.json',
    ):
        assert needle in text


def test_diagnostic_privacy_guards_are_explicit() -> None:
    text = BACKEND.read_text(encoding="utf-8")
    assert '"raw_embeddings": False' in text
    assert '"rtsp_credentials": False' in text
    assert '"push_tokens": False' in text
    assert 'MAX_SCREEN_BYTES' in text
    assert '_SECRET_KEYS' in text


def test_interrupted_session_survives_native_crash_or_restart() -> None:
    text = BACKEND.read_text(encoding="utf-8")
    assert '_finalize_interrupted' in text
    assert '"interrupted"' in text
    assert 'backend restarted or process ended before diagnostic stop' in text


def test_frontend_records_ux_media_api_and_markers() -> None:
    text = FRONTEND.read_text(encoding="utf-8")
    for needle in (
        "timeline.next_media",
        "timeline.previous_media",
        "performance.long_task",
        "performance.raf_fps",
        "media.waiting",
        "media.stalled",
        "frontend.state",
        "user.problem_marker.client",
        "getVideoPlaybackQuality",
        "getDisplayMedia",
    ):
        assert needle in text
    assert "innerText" not in text
    assert "textContent" in text  # UI/status only; form/user text is not harvested.


def test_diagnostic_fetch_does_not_self_trace_recursively() -> None:
    text = FRONTEND.read_text(encoding="utf-8")
    assert "nativeFetch" in text
    assert "includes('/api/diagnostics/session/')" in text
    assert "window.fetch = async function poiDiagnosticFetch" in text


def test_loader_and_service_worker_include_v70_assets() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    sw = SW.read_text(encoding="utf-8")
    for asset in ("/v70-full-diagnostics.js", "/v70-full-diagnostics.css"):
        assert asset in loader
        assert asset in sw
    assert "personofinterest-v7.0-full-diagnostic-session" in sw


def test_backend_patch_is_attached_without_touching_core_vision() -> None:
    patch = PATCH.read_text(encoding="utf-8")
    timeline_patch = (ROOT / "backend" / "app" / "timeline_analysis_patch.py").read_text(encoding="utf-8")
    assert "include_router(diagnostics_router)" in patch
    assert "install_session_diagnostics()" in timeline_patch

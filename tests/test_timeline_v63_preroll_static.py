from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_preroll_is_installed_before_storage_disk_guard():
    init = text("backend/app/__init__.py")
    assert "_install_recording_preroll_patch()" in init
    assert init.index("_install_recording_preroll_patch()") < init.index("_install_storage_recording_patch()")


def test_event_mode_uses_rolling_buffer_and_half_window():
    source = text("backend/app/recording_preroll_patch.py")
    assert "BUFFER_SEGMENT_SECONDS" in source
    assert "half = total_duration / 2.0" in source
    assert "start_at = event_at - timedelta(seconds=half)" in source
    assert "end_at = event_at + timedelta(seconds=half)" in source
    assert "-f\", \"segment" in source
    assert "mode=\"event\"" in source


def test_event_clip_is_consolidated_as_real_recording():
    source = text("backend/app/recording_preroll_patch.py")
    assert "INSERT INTO recording_files" in source
    assert "'event'" in source
    assert "source_event_id" in source
    assert "-f\", \"concat" in source


def test_merged_clip_tracks_every_event_explicitly():
    source = text("backend/app/recording_preroll_patch.py")
    assert "event_ids: list[int]" in source
    assert "recording_event_links" in source
    assert "current.event_ids.append(event_id)" in source
    assert "for event_id in pending.event_ids" in source


def test_failed_copy_concat_retries_with_reencode():
    source = text("backend/app/recording_preroll_patch.py")
    assert "fallback_command" in source
    assert '"-c:v", "libx264"' in source
    assert '"-c:a", "aac"' in source


def test_new_events_are_queued_before_due_clip_is_finalized():
    source = text("backend/app/recording_preroll_patch.py")
    reconcile = source[source.index("def reconcile_with_preroll"):source.index("def status_with_preroll")]
    assert reconcile.index("for event in self._new_events()") < reconcile.index("_finalize_due(self)")


def test_editor_tracks_are_separate():
    js = text("frontend/v63-timeline-tracks.js")
    css = text("frontend/v63-timeline-tracks.css")
    assert "poiV63ContinuousTrack" in js
    assert "poiV63ClipTrack" in js
    assert "poiV63EventTrack" in js
    assert "poi-v63-range clip" in js
    assert ".poi-v63-track.clips" in css
    assert ".poi-v63-track.events" in css


def test_marker_selection_scrolls_matching_thumb():
    js = text("frontend/v63-timeline-tracks.js")
    assert "function scrollThumb(eventId)" in js
    assert "strip.scrollTo" in js
    assert "function selectEvent(event" in js
    assert "syncSelection(event.id)" in js


def test_timeline_entry_focuses_live_or_last_event():
    js = text("frontend/v63-timeline-tracks.js")
    assert "async function focusLatest()" in js
    assert "T.data.recording?.mode === 'continuous'" in js
    assert "const last = events[events.length - 1]" in js


def test_next_previous_navigation_knows_event_clips():
    js = text("frontend/v63-timeline-tracks.js")
    assert "function navigationItems()" in js
    assert "type: 'clip'" in js
    assert "exactEventClipMap" in js
    assert "poiHybridNext,#poiHybridPrev" in js


def test_person_picker_fetches_registered_people_directly():
    js = text("frontend/v63-timeline-tracks.js")
    assert "/api/persons?_=" in js
    assert "Selecione uma pessoa" in js
    assert "＋ Novo nome" in js


def test_continuous_video_can_overlay_or_pause_on_events():
    js = text("frontend/v63-timeline-tracks.js")
    assert "poiV63PauseEvents" in js
    assert "showOverlay(event, pause)" in js
    assert "video.addEventListener('timeupdate'" in js

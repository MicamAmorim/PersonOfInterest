from pathlib import Path


def test_v60_filters_false_positive_events_and_recordings_at_source():
    text = Path('frontend/v60-timeline-player.js').read_text(encoding='utf-8')
    assert 'function isFalsePositiveEvent' in text
    assert 'function visibleRecordings' in text
    assert "String(rec.mode || '') !== 'event'" in text
    assert 'fp.has(Number(rec.source_event_id))' in text
    assert 'renderCoverage(); renderEvents();' in text


def test_v60_exposes_exact_id_selection_core():
    text = Path('frontend/v60-timeline-player.js').read_text(encoding='utf-8')
    assert 'async function selectRecordingById' in text
    assert 'async function selectEventById' in text
    assert 'recording: rec' in text
    assert 'window.poiTimelineCore' in text
    assert 'selectRecordingById, selectEventById, selectSecond' in text
    select_block = text[text.index('async function selectSecond'):text.index('function updatePlayhead')]
    assert 'Math.round(V60.currentSecond)' not in select_block


def test_v73_filters_false_positive_artifacts_as_secondary_guard():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert "state === 'false_positive'" in text
    assert "label === 'falso positivo'" in text
    assert '#poiTimelinePlayer [data-event-id]' in text
    assert '#poiCoverageTrack [data-recording-id]' in text
    assert '#poiV63ClipTrack [data-v63-clip]' in text
    assert "overlaySaysFp" in text
    assert 'poiV66BBox' in text


def test_v73_navigation_is_index_based_and_uses_actual_media_first():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert 'function itemKey' in text
    assert 'function currentMediaKey' in text
    assert 'function neighborByIndex' in text
    assert 'items[index + direction]' in text
    block = text[text.index('function currentMediaKey'):text.index('function neighborByIndex')]
    assert block.index("video.dataset.recordingId") < block.index('S.currentKey')


def test_v73_selects_recording_by_id_without_synthetic_event_click():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert 'timelineCore?.selectRecordingById' in text
    assert 'timelineCore.selectRecordingById(Number(item.rec.id)' in text
    assert 'timelineCore?.selectEventById' in text
    assert 'eventNode.click()' not in text
    assert 'resumeHybridSoon' not in text


def test_v73_owns_previous_next_and_preserves_actual_play_state():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert "event.target?.closest?.('#poiHybridNext')" in text
    assert "event.target?.closest?.('#poiHybridPrev')" in text
    assert 'event.stopImmediatePropagation()' in text
    assert 'function videoActuallyPlaying' in text
    assert 'autoplay: Boolean(resume)' in text


def test_v73_loads_before_v69_navigation_owner():
    text = Path('frontend/v49-identity-diagnostics.js').read_text(encoding='utf-8')
    assert '/v73-false-positive-timeline-filter.js' in text
    assert text.index('/v73-false-positive-timeline-filter.js') < text.index('/v69-tonho-media-navigation.js')


def test_v74_cache_is_bumped_and_scripts_are_cached():
    text = Path('frontend/sw.js').read_text(encoding='utf-8')
    assert "personofinterest-v7.4.0-id-driven-timeline" in text
    assert '/v60-timeline-player.js' in text
    assert '/v73-false-positive-timeline-filter.js' in text

from pathlib import Path


def test_v73_filters_false_positive_artifacts_and_event_clips():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert "state === 'false_positive'" in text
    assert "label === 'falso positivo'" in text
    assert '#poiTimelinePlayer [data-event-id]' in text
    assert '#poiEventStrip [data-event-card]' in text
    assert '#poiCoverageTrack [data-recording-id]' in text
    assert 'isHiddenFalsePositiveRecording' in text
    assert 'clearHiddenCurrentRecording' in text
    assert 'poiV66BBox' in text


def test_v73_navigation_is_index_based_and_keeps_stable_media_key():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert 'function itemKey' in text
    assert 'function currentMediaKey' in text
    assert 'function neighborByIndex' in text
    assert 'items[index + direction]' in text
    assert 'S.navKey = itemKey(item)' in text
    assert 'jumpMediaDeterministic(next ? 1 : -1)' in text


def test_v73_selects_exact_event_recording_before_moving_needle():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert 'function exactEventNode' in text
    assert 'function pinRecordingStart' in text
    assert 'eventNode.click()' in text
    assert 'Number(video.dataset.recordingId || 0) !== recId' in text
    assert 'video.currentTime =' in text
    assert 'syncNeedleOnly(second)' in text
    needle_block = text[text.index('function syncNeedleOnly'):text.index('function seekFallback')]
    assert "dispatchEvent(new Event('input'" in needle_block
    assert "dispatchEvent(new Event('change'" not in needle_block


def test_v73_owns_previous_next():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert "event.target?.closest?.('#poiHybridNext')" in text
    assert "event.target?.closest?.('#poiHybridPrev')" in text
    assert 'event.stopImmediatePropagation()' in text


def test_v73_loads_before_v69_navigation_owner():
    text = Path('frontend/v49-identity-diagnostics.js').read_text(encoding='utf-8')
    assert '/v73-false-positive-timeline-filter.js' in text
    assert text.index('/v73-false-positive-timeline-filter.js') < text.index('/v69-tonho-media-navigation.js')


def test_v73_cache_is_bumped_and_script_is_cached():
    text = Path('frontend/sw.js').read_text(encoding='utf-8')
    assert "personofinterest-v7.3.3-exact-recording-navigation" in text
    assert '/v73-false-positive-timeline-filter.js' in text

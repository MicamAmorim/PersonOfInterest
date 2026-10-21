from pathlib import Path


def test_v73_filters_false_positive_artifacts_and_event_clips():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert "identity_state || '') === 'false_positive'" in text
    assert '#poiV63ClipTrack [data-event-id]' in text
    assert '#poiV63EventTrack [data-event-id]' in text
    assert '#poiEventStrip [data-event-card]' in text
    assert '#poiCoverageTrack [data-recording-id]' in text
    assert 'isHiddenFalsePositiveRecording' in text
    assert 'clearHiddenCurrentRecording' in text
    assert 'poiV66BBox' in text


def test_v73_owns_previous_next_and_uses_safe_fractional_seek():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert "event.target?.closest?.('#poiHybridNext')" in text
    assert "event.target?.closest?.('#poiHybridPrev')" in text
    assert 'event.stopImmediatePropagation()' in text
    assert 'void jumpTemporal(next ? 1 : -1)' in text
    assert "scrubber.step = '0.01'" in text
    assert 'safeTemporalSecond' in text
    assert 'start + margin' in text
    seek_block = text[text.index('function seekExact'):text.index('function syncEventSelection')]
    assert 'Math.round' not in seek_block


def test_v73_loads_before_v69_navigation_owner():
    text = Path('frontend/v49-identity-diagnostics.js').read_text(encoding='utf-8')
    assert '/v73-false-positive-timeline-filter.js' in text
    assert text.index('/v73-false-positive-timeline-filter.js') < text.index('/v69-tonho-media-navigation.js')


def test_v73_cache_is_bumped_and_script_is_cached():
    text = Path('frontend/sw.js').read_text(encoding='utf-8')
    assert "personofinterest-v7.3.1-timeline-filter-navigation-fix" in text
    assert '/v73-false-positive-timeline-filter.js' in text

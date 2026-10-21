from pathlib import Path


def test_v73_filters_all_false_positive_timeline_artifacts():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert "state === 'false_positive'" in text
    assert "label === 'falso positivo'" in text
    assert "#poiTimelinePlayer [data-event-id]" in text
    assert '#poiEventStrip [data-event-card]' in text
    assert '#poiCoverageTrack [data-recording-id]' in text
    assert 'isHiddenFalsePositiveRecording' in text
    assert 'clearHiddenCurrentRecording' in text
    assert 'poiV66BBox' in text
    assert 'subtree: true' in text
    assert "attributeFilter: ['hidden', 'class', 'style', 'data-event-id', 'data-event-card', 'data-recording-id']" in text


def test_v73_previous_next_are_index_based_and_symmetric():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert "event.target?.closest?.('#poiHybridNext')" in text
    assert "event.target?.closest?.('#poiHybridPrev')" in text
    assert 'event.stopImmediatePropagation()' in text
    assert 'jumpMediaDeterministic' in text
    assert 'neighborByIndex' in text
    assert 'items[index + direction]' in text
    assert 'currentMediaKey' in text
    assert 'itemKey' in text
    assert 'temporalTarget' not in text
    assert ".35" not in text[text.index('function neighborByIndex'):text.index('function resumeHybridSoon')]


def test_v73_seeks_to_real_media_start_without_integer_rounding():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert "scrubber.step = '0.01'" in text
    assert 'start + .02' in text
    seek_block = text[text.index('function seekExact'):text.index('function syncEventSelection')]
    assert 'Math.round' not in seek_block


def test_v73_loads_before_v69_navigation_owner():
    text = Path('frontend/v49-identity-diagnostics.js').read_text(encoding='utf-8')
    assert '/v73-false-positive-timeline-filter.js' in text
    assert text.index('/v73-false-positive-timeline-filter.js') < text.index('/v69-tonho-media-navigation.js')


def test_v73_cache_is_bumped_and_script_is_cached():
    text = Path('frontend/sw.js').read_text(encoding='utf-8')
    assert "personofinterest-v7.3.2-deterministic-media-navigation" in text
    assert '/v73-false-positive-timeline-filter.js' in text

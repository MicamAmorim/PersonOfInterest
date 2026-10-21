from pathlib import Path


def test_v73_filters_false_positive_artifacts_and_navigation():
    text = Path('frontend/v73-false-positive-timeline-filter.js').read_text(encoding='utf-8')
    assert "identity_state || '') === 'false_positive'" in text
    assert '#poiV63ClipTrack [data-event-id]' in text
    assert '#poiV63EventTrack [data-event-id]' in text
    assert '#poiEventStrip [data-event-card]' in text
    assert 'isHiddenFalsePositive(rawTarget)' in text
    assert 'event.stopImmediatePropagation()' in text
    assert 'poiV66BBox' in text


def test_v73_loads_before_v69_navigation_owner():
    text = Path('frontend/v49-identity-diagnostics.js').read_text(encoding='utf-8')
    assert '/v73-false-positive-timeline-filter.js' in text
    assert text.index('/v73-false-positive-timeline-filter.js') < text.index('/v69-tonho-media-navigation.js')


def test_v73_is_cached_by_service_worker():
    text = Path('frontend/sw.js').read_text(encoding='utf-8')
    assert "personofinterest-v7.3-false-positive-timeline-filter" in text
    assert '/v73-false-positive-timeline-filter.js' in text

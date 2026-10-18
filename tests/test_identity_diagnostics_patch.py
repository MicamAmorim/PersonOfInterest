import numpy as np

from backend.app.identity_diagnostics_patch import _pair_diagnostics


def _sample(sample_id, event_id, person_id, vector, quality=0.9, source="manual_verified"):
    value = np.asarray(vector, dtype=np.float32)
    value = value / np.linalg.norm(value)
    return {
        "id": sample_id,
        "event_id": event_id,
        "person_id": person_id,
        "embedding": value.tobytes(),
        "quality": quality,
        "source": source,
    }


def test_pair_diagnostics_flags_cross_person_closer_than_same_person():
    samples = [
        _sample(1, 101, 10, [1.0, 0.0]),
        _sample(2, 102, 10, [0.0, 1.0]),
        _sample(3, 103, 20, [0.99, 0.01]),
    ]
    per_sample, pairs = _pair_diagnostics(samples, 100)
    row = next(item for item in per_sample if item["sample_id"] == 1)
    assert row["suspect_label"] is True
    assert row["nearest_other_person_id"] == 20
    assert any(item["same_person"] == 1 for item in pairs)
    assert any(item["same_person"] == 0 for item in pairs)

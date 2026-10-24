import math
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import body_identity as bi
from app.tracking_v5_patch import (
    PersistentCentroidTracker,
    aggregate_temporal_body,
    robust_rank_probable,
)


def vector_with_cosine(value: float) -> np.ndarray:
    value = float(value)
    return np.asarray([value, math.sqrt(max(0.0, 1.0 - value * value)), 0.0], dtype=np.float32)


class PersistentTrackingV5Tests(unittest.TestCase):
    def test_lost_track_is_reassociated_instead_of_creating_new_event_track(self):
        tracker = PersistentCentroidTracker(high_confidence=0.42)
        shape = (480, 640, 3)
        first = tracker.update([((120, 80, 100, 230), 0.91)], shape)
        self.assertEqual(len(first), 1)
        track_id = first[0].id

        for _ in range(5):
            tracker.update([], shape)
        self.assertIn(track_id, tracker.tracks)
        self.assertGreater(tracker.tracks[track_id].missed, 0)

        recovered = tracker.update([((145, 86, 102, 228), 0.88)], shape)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].id, track_id)
        self.assertEqual(recovered[0].missed, 0)
        self.assertGreaterEqual(recovered[0].hits, 2)

    def test_track_is_finalized_only_after_persistent_reassociation_window(self):
        tracker = PersistentCentroidTracker(high_confidence=0.42)
        shape = (480, 640, 3)
        track_id = tracker.update([((100, 70, 100, 220), 0.9)], shape)[0].id
        for _ in range(tracker.max_missed):
            tracker.update([], shape)
        self.assertIn(track_id, tracker.tracks)
        tracker.update([], shape)
        self.assertNotIn(track_id, tracker.tracks)
        self.assertEqual([track.id for track in tracker.just_ended], [track_id])

    def test_temporal_body_aggregation_returns_normalized_stable_track_embedding(self):
        observations = [
            (np.asarray([1.0, 0.0, 0.0], dtype=np.float32), 0.86, 1.0),
            (np.asarray([0.99, 0.08, 0.0], dtype=np.float32), 0.82, 2.0),
            (np.asarray([0.98, -0.10, 0.0], dtype=np.float32), 0.80, 3.0),
            (np.asarray([0.95, 0.15, 0.0], dtype=np.float32), 0.72, 4.0),
        ]
        embedding, quality, support, stability = aggregate_temporal_body(observations)
        self.assertIsNotNone(embedding)
        self.assertAlmostEqual(float(np.linalg.norm(embedding)), 1.0, places=5)
        self.assertGreaterEqual(support, 3)
        self.assertGreater(stability, 0.95)
        self.assertGreater(quality, 0.65)

    def test_robust_person_score_prefers_consistent_anchors_over_one_accidental_maximum(self):
        query = np.asarray([1.0, 0.0, 0.0], dtype=np.float32)
        gallery = []
        for cosine in (0.96, 0.56, 0.54):
            gallery.append({
                "person_id": 1,
                "embedding": bi._vector_to_blob(vector_with_cosine(cosine)),
                "quality": 0.9,
                "source": "manual_verified",
            })
        for cosine in (0.83, 0.81, 0.80):
            gallery.append({
                "person_id": 2,
                "embedding": bi._vector_to_blob(vector_with_cosine(cosine)),
                "quality": 0.9,
                "source": "manual_verified",
            })
        person_id, confidence, source = robust_rank_probable(query, 0.95, gallery)
        self.assertEqual(person_id, 2)
        self.assertIsNotNone(confidence)
        self.assertEqual(source, "body_reid")


if __name__ == "__main__":
    unittest.main()

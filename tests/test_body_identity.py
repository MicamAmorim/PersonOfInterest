import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.body_identity import BodyIdentityManager, _vector_to_blob, rank_hard_negative, rank_probable


class BodyIdentityTests(unittest.TestCase):
    def test_body_match_is_probable_and_face_linked_reference_wins(self):
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        gallery = [
            {
                "person_id": 1,
                "embedding": _vector_to_blob(np.array([0.78, 0.62, 0.0], dtype=np.float32)),
                "quality": 0.9,
                "source": "manual_verified",
            },
            {
                "person_id": 2,
                "embedding": _vector_to_blob(np.array([0.80, 0.60, 0.0], dtype=np.float32)),
                "quality": 0.9,
                "source": "face_verified",
            },
        ]
        person_id, confidence, source = rank_probable(query, 0.9, gallery)
        self.assertEqual(person_id, 2)
        self.assertIsNotNone(confidence)
        self.assertEqual(source, "face_linked_body")

    def test_ambiguous_body_match_is_not_promoted(self):
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        gallery = [
            {
                "person_id": 1,
                "embedding": _vector_to_blob(np.array([0.82, 0.57, 0.0], dtype=np.float32)),
                "quality": 0.9,
                "source": "manual_verified",
            },
            {
                "person_id": 2,
                "embedding": _vector_to_blob(np.array([0.81, 0.58, 0.0], dtype=np.float32)),
                "quality": 0.9,
                "source": "manual_verified",
            },
        ]
        person_id, confidence, source = rank_probable(query, 0.9, gallery)
        self.assertIsNone(person_id)
        self.assertIsNone(confidence)
        self.assertIsNone(source)

    def test_repeated_manual_negatives_auto_reject_similar_object(self):
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        negatives = [
            {
                "embedding": _vector_to_blob(np.array([0.998, 0.04, 0.0], dtype=np.float32)),
                "quality": 0.9,
                "bbox_json": '{"x":10,"y":10,"w":100,"h":200}',
            },
            {
                "embedding": _vector_to_blob(np.array([0.995, 0.06, 0.0], dtype=np.float32)),
                "quality": 0.85,
                "bbox_json": '{"x":12,"y":11,"w":99,"h":201}',
            },
        ]
        rejected, score, reason = rank_hard_negative(
            query,
            0.9,
            negatives,
            [],
            '{"x":11,"y":10,"w":100,"h":200}',
        )
        self.assertTrue(rejected)
        self.assertIsNotNone(score)
        self.assertEqual(reason, "repeated_reviewed_negative")

    def test_one_negative_needs_extreme_similarity_and_same_region(self):
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        negative = [{
            "embedding": _vector_to_blob(np.array([0.9999, 0.01, 0.0], dtype=np.float32)),
            "quality": 1.0,
            "bbox_json": '{"x":20,"y":20,"w":80,"h":160}',
        }]
        rejected, _, reason = rank_hard_negative(
            query,
            1.0,
            negative,
            [],
            '{"x":21,"y":21,"w":80,"h":160}',
        )
        self.assertTrue(rejected)
        self.assertEqual(reason, "stationary_reviewed_negative")

        rejected_elsewhere, _, _ = rank_hard_negative(
            query,
            1.0,
            negative,
            [],
            '{"x":400,"y":200,"w":80,"h":160}',
        )
        self.assertFalse(rejected_elsewhere)

    def test_verified_human_reference_can_veto_ambiguous_negative(self):
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        negatives = [
            {
                "embedding": _vector_to_blob(np.array([0.94, 0.34, 0.0], dtype=np.float32)),
                "quality": 0.9,
                "bbox_json": '{"x":10,"y":10,"w":100,"h":200}',
            },
            {
                "embedding": _vector_to_blob(np.array([0.93, 0.36, 0.0], dtype=np.float32)),
                "quality": 0.9,
                "bbox_json": '{"x":12,"y":10,"w":100,"h":200}',
            },
        ]
        humans = [{
            "person_id": 7,
            "embedding": _vector_to_blob(np.array([0.999, 0.03, 0.0], dtype=np.float32)),
            "quality": 1.0,
            "source": "face_verified",
        }]
        rejected, _, reason = rank_hard_negative(
            query,
            1.0,
            negatives,
            humans,
            '{"x":11,"y":10,"w":100,"h":200}',
        )
        self.assertFalse(rejected)
        self.assertEqual(reason, "human_reference_wins")

    def test_fixed_batch_osnet_repeats_one_crop_and_returns_one_embedding(self):
        class FixedBatchSession:
            def __init__(self):
                self.seen_shape = None

            def run(self, _outputs, feed):
                tensor = next(iter(feed.values()))
                self.seen_shape = tuple(tensor.shape)
                return [np.tile(np.asarray([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32), (tensor.shape[0], 1))]

        manager = BodyIdentityManager()
        manager._session = FixedBatchSession()
        manager._input_name = "input"
        manager._nchw = True
        manager._batch_size = 16
        manager._ensure_model = lambda: None

        crop = np.zeros((300, 160, 3), dtype=np.uint8)
        embedding = manager._embed_crop(crop)

        self.assertEqual(manager._session.seen_shape, (16, 3, 256, 128))
        self.assertEqual(embedding.shape, (4,))
        self.assertAlmostEqual(float(np.linalg.norm(embedding)), 1.0, places=5)


if __name__ == "__main__":
    unittest.main()

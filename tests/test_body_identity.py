import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.body_identity import _vector_to_blob, rank_probable


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


if __name__ == "__main__":
    unittest.main()

import unittest

import numpy as np

from app.alerts import AlertManager
from app.identity import _cosine, _normalize
from app.models import AlertRuleCreate


class IdentityMathTests(unittest.TestCase):
    def test_normalized_cosine(self):
        a = _normalize(np.array([2.0, 0.0, 0.0], dtype=np.float32))
        b = _normalize(np.array([4.0, 0.0, 0.0], dtype=np.float32))
        c = _normalize(np.array([0.0, 1.0, 0.0], dtype=np.float32))
        self.assertAlmostEqual(_cosine(a, b), 1.0, places=5)
        self.assertAlmostEqual(_cosine(a, c), 0.0, places=5)


class AlertRuleTests(unittest.TestCase):
    def test_cross_midnight_unknown_rule(self):
        manager = AlertManager()
        rule = {
            "camera_id": 2,
            "person_id": None,
            "unknown_only": 1,
            "start_time": "23:00",
            "end_time": "06:00",
            "weekdays_json": "[0,1,2,3,4,5,6]",
            "timezone": "UTC",
        }
        event = {
            "camera_id": 2,
            "person_id": None,
            "created_at": "2026-10-17T02:30:00+00:00",
        }
        self.assertTrue(manager._matches(rule, event))
        event["created_at"] = "2026-10-17T14:30:00+00:00"
        self.assertFalse(manager._matches(rule, event))

    def test_rule_rejects_unknown_and_specific_person(self):
        with self.assertRaises(ValueError):
            AlertRuleCreate(name="x", unknown_only=True, person_id=1)


if __name__ == "__main__":
    unittest.main()

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.spatial_alerts import (
    SpatialAlertManager,
    _crosses_polyline,
    _inside_polygon,
    _movement_matches_arrow,
)


class _Track:
    id = 7
    event_id = None


class SpatialAlertGeometryTests(unittest.TestCase):
    def test_crosses_polyline(self):
        line = [(0.2, 0.5), (0.8, 0.5)]
        self.assertTrue(_crosses_polyline((0.5, 0.3), (0.5, 0.7), line))
        self.assertFalse(_crosses_polyline((0.1, 0.3), (0.1, 0.7), line))

    def test_direction_arrow_filters_reverse_crossing(self):
        arrow_from = (0.5, 0.35)
        arrow_to = (0.5, 0.75)
        self.assertTrue(_movement_matches_arrow((0.5, 0.3), (0.5, 0.7), arrow_from, arrow_to))
        self.assertFalse(_movement_matches_arrow((0.5, 0.7), (0.5, 0.3), arrow_from, arrow_to))

    def test_point_in_polygon_both_edge_orientations(self):
        clockwise = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
        counterclockwise = list(reversed(clockwise))
        for polygon in (clockwise, counterclockwise):
            self.assertTrue(_inside_polygon((0.5, 0.5), polygon))
            self.assertTrue(_inside_polygon((0.2, 0.5), polygon))
            self.assertFalse(_inside_polygon((0.05, 0.5), polygon))

    def test_polyline_supports_multiple_segments(self):
        line = [(0.1, 0.3), (0.5, 0.5), (0.9, 0.3)]
        self.assertTrue(_crosses_polyline((0.7, 0.1), (0.7, 0.6), line))

    def test_outside_rule_requires_real_exit_then_dwell(self):
        manager = SpatialAlertManager()
        fired = []
        manager._trigger = lambda *args: fired.append(args[-1])  # type: ignore[method-assign]
        rule = {
            "id": 1,
            "zone_mode": "outside",
            "dwell_seconds": 2.0,
            "cooldown_seconds": 0.0,
        }
        geometry = {
            "points": [
                {"x": 0.2, "y": 0.2},
                {"x": 0.8, "y": 0.2},
                {"x": 0.8, "y": 0.8},
                {"x": 0.2, "y": 0.8},
            ]
        }
        state = {
            "previous": None,
            "condition_since": None,
            "fired": False,
            "last_trigger": 0.0,
            "last_seen": 0.0,
            "was_inside": False,
        }

        # A track first observed outside is not an exit.
        manager._process_zone(rule, state, _Track(), 1, "Cam", (0.9, 0.5), geometry, 1.0)
        manager._process_zone(rule, state, _Track(), 1, "Cam", (0.9, 0.5), geometry, 5.0)
        self.assertEqual(fired, [])

        # Seeing it inside arms the rule. Leaving starts the dwell timer.
        manager._process_zone(rule, state, _Track(), 1, "Cam", (0.5, 0.5), geometry, 6.0)
        self.assertTrue(state["was_inside"])
        manager._process_zone(rule, state, _Track(), 1, "Cam", (0.9, 0.5), geometry, 7.0)
        self.assertEqual(fired, [])
        manager._process_zone(rule, state, _Track(), 1, "Cam", (0.9, 0.5), geometry, 9.1)
        self.assertEqual(fired, ["zone_outside"])


if __name__ == "__main__":
    unittest.main()

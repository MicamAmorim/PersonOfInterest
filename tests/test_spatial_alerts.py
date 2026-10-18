import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.spatial_alerts import (
    _crosses_polyline,
    _inside_polygon,
    _movement_matches_arrow,
)


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


if __name__ == "__main__":
    unittest.main()

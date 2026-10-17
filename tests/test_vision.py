import unittest

from backend.app.vision import CentroidTracker


class VisionTrackerTests(unittest.TestCase):
    def test_track_id_is_stable_for_nearby_detection(self):
        tracker = CentroidTracker()
        first = tracker.update([((100, 100, 80, 180), 0.9)], (480, 640, 3))
        self.assertEqual(len(first), 1)
        track_id = first[0].id

        second = tracker.update([((108, 104, 80, 180), 0.88)], (480, 640, 3))
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].id, track_id)
        self.assertGreaterEqual(second[0].hits, 2)

    def test_far_detection_creates_another_track(self):
        tracker = CentroidTracker()
        tracker.update([((20, 20, 70, 160), 0.8)], (480, 640, 3))
        tracks = tracker.update([((500, 200, 70, 160), 0.8)], (480, 640, 3))
        self.assertGreaterEqual(len(tracks), 1)
        self.assertTrue(any(t.id != 1 for t in tracks))


if __name__ == "__main__":
    unittest.main()

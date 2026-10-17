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
        self.assertTrue(second[0].control_valid)

    def test_far_detection_creates_another_track(self):
        tracker = CentroidTracker()
        tracker.update([((20, 20, 70, 160), 0.8)], (480, 640, 3))
        tracks = tracker.update([((500, 200, 70, 160), 0.8)], (480, 640, 3))
        self.assertGreaterEqual(len(tracks), 1)
        self.assertTrue(any(t.id != 1 for t in tracks))

    def test_low_confidence_detection_cannot_create_track(self):
        tracker = CentroidTracker(high_confidence=0.42)
        tracks = tracker.update([((100, 100, 80, 180), 0.25)], (480, 640, 3))
        self.assertEqual(tracks, [])

    def test_low_confidence_detection_can_rescue_existing_track_without_ptz(self):
        tracker = CentroidTracker(high_confidence=0.42)
        stable = tracker.update([((100, 100, 80, 180), 0.9)], (480, 640, 3))[0]
        tracker.update([((106, 103, 80, 180), 0.88)], (480, 640, 3))
        rescued = tracker.update([((112, 108, 78, 176), 0.25)], (480, 640, 3))[0]
        self.assertEqual(rescued.id, stable.id)
        self.assertEqual(rescued.missed, 0)
        self.assertFalse(rescued.control_valid)
        self.assertEqual(rescued.control_reason, "low_confidence")

    def test_partial_edge_box_does_not_drive_control(self):
        tracker = CentroidTracker()
        tracker.update([((220, 120, 90, 210), 0.9)], (480, 640, 3))
        stable = tracker.update([((224, 122, 90, 208), 0.9)], (480, 640, 3))[0]
        self.assertTrue(stable.control_valid)
        previous_center = (stable.smooth_cx, stable.smooth_cy)

        partial = tracker.update([((250, 430, 70, 50), 0.55)], (480, 640, 3))[0]
        self.assertFalse(partial.control_valid)
        self.assertEqual((partial.smooth_cx, partial.smooth_cy), previous_center)

    def test_large_geometry_jump_is_rejected_for_ptz(self):
        tracker = CentroidTracker()
        tracker.update([((200, 100, 100, 220), 0.9)], (480, 640, 3))
        stable = tracker.update([((205, 104, 100, 220), 0.9)], (480, 640, 3))[0]
        self.assertTrue(stable.control_valid)
        center = (stable.smooth_cx, stable.smooth_cy)

        jumped = tracker.update([((420, 20, 30, 60), 0.5)], (480, 640, 3))
        original = next(track for track in jumped if track.id == stable.id)
        self.assertFalse(original.control_valid)
        self.assertEqual((original.smooth_cx, original.smooth_cy), center)


if __name__ == "__main__":
    unittest.main()

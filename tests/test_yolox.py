import unittest

import numpy as np

from backend.app.yolox_detector import YoloXPersonDetector


class YoloXDetectorTests(unittest.TestCase):
    def test_nms_suppresses_overlapping_boxes(self):
        boxes = np.array(
            [
                [10.0, 10.0, 110.0, 210.0],
                [14.0, 14.0, 108.0, 208.0],
                [250.0, 30.0, 330.0, 200.0],
            ],
            dtype=np.float32,
        )
        scores = np.array([0.91, 0.80, 0.72], dtype=np.float32)
        keep = YoloXPersonDetector._nms(boxes, scores, 0.45)
        self.assertEqual(keep, [0, 2])

    def test_nms_empty(self):
        boxes = np.empty((0, 4), dtype=np.float32)
        scores = np.empty((0,), dtype=np.float32)
        self.assertEqual(YoloXPersonDetector._nms(boxes, scores, 0.45), [])


if __name__ == "__main__":
    unittest.main()

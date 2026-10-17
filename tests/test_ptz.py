import unittest

from backend.app.ptz import logical_to_onvif


class PTZMappingTests(unittest.TestCase):
    def test_icsee_axis_rotation(self):
        self.assertEqual(logical_to_onvif(1, 0), (0.0, 1.0))      # right
        self.assertEqual(logical_to_onvif(-1, 0), (0.0, -1.0))    # left
        self.assertEqual(logical_to_onvif(0, 1), (-1.0, 0.0))     # up
        self.assertEqual(logical_to_onvif(0, -1), (1.0, 0.0))     # down

    def test_mapping_clamps_input(self):
        self.assertEqual(logical_to_onvif(3, -4), (1.0, 1.0))


if __name__ == "__main__":
    unittest.main()

import unittest

from backend.app.ptz import direction_from_vector, sofia_hash


class PTZDirectionTests(unittest.TestCase):
    def test_cardinal_directions(self):
        self.assertEqual(direction_from_vector(1, 0), "DirectionRight")
        self.assertEqual(direction_from_vector(-1, 0), "DirectionLeft")
        self.assertEqual(direction_from_vector(0, 1), "DirectionUp")
        self.assertEqual(direction_from_vector(0, -1), "DirectionDown")

    def test_diagonal_directions(self):
        self.assertEqual(direction_from_vector(1, 1), "DirectionRightUp")
        self.assertEqual(direction_from_vector(1, -1), "DirectionRightDown")
        self.assertEqual(direction_from_vector(-1, 1), "DirectionLeftUp")
        self.assertEqual(direction_from_vector(-1, -1), "DirectionLeftDown")

    def test_deadzone(self):
        self.assertIsNone(direction_from_vector(0.05, -0.05))

    def test_sofia_hash_is_stable(self):
        self.assertEqual(len(sofia_hash("")), 8)
        self.assertEqual(sofia_hash(""), "tlJwpbo6")


if __name__ == "__main__":
    unittest.main()

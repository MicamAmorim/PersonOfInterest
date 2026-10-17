import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.assistant import casual_message, daypart_for, greeting_message


class AssistantGreetingTests(unittest.TestCase):
    def test_daypart_boundaries(self):
        cases = [
            (4, "night", "Boa noite"),
            (5, "morning", "Bom dia"),
            (11, "morning", "Bom dia"),
            (12, "afternoon", "Boa tarde"),
            (17, "afternoon", "Boa tarde"),
            (18, "night", "Boa noite"),
            (23, "night", "Boa noite"),
        ]
        for hour, expected_part, expected_greeting in cases:
            with self.subTest(hour=hour):
                part, greeting = daypart_for(datetime(2026, 10, 17, hour, 0, tzinfo=timezone.utc))
                self.assertEqual(part, expected_part)
                self.assertEqual(greeting, expected_greeting)

    def test_known_greeting_is_assertive(self):
        self.assertEqual(greeting_message("Miquéias", "Bom dia", probable=False), "Bom dia, Miquéias.")
        self.assertEqual(casual_message("Miquéias", probable=False), "Oi, Miquéias, estou de olho!")

    def test_probable_greeting_keeps_uncertainty(self):
        self.assertEqual(greeting_message("Miquéias", "Boa tarde", probable=True), "Boa tarde, Miquéias?")
        self.assertEqual(casual_message("Miquéias", probable=True), "Oi, Miquéias? Estou de olho!")


if __name__ == "__main__":
    unittest.main()

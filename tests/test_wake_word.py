import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.wake_word import matches_wake_phrase, normalize_phrase


class WakeWordTests(unittest.TestCase):
    def test_normalizes_accents_and_punctuation(self):
        self.assertEqual(normalize_phrase("  Oi, Tônho!  "), "oi tonho")

    def test_matches_exact_activation_phrase(self):
        self.assertTrue(matches_wake_phrase("Oi, Tonho!"))
        self.assertTrue(matches_wake_phrase("Ei... oi Tonho, está aí?"))

    def test_accepts_common_whisper_spelling(self):
        self.assertTrue(matches_wake_phrase("Oi, Tonio!"))
        self.assertTrue(matches_wake_phrase("Oi Antônio"))

    def test_does_not_trigger_on_generic_greeting(self):
        self.assertFalse(matches_wake_phrase("Oi, tudo bem?"))
        self.assertFalse(matches_wake_phrase("Boa noite, Tonho"))
        self.assertFalse(matches_wake_phrase("Tonho"))


if __name__ == "__main__":
    unittest.main()

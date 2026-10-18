import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.assistant_tools import detect_intent, normalize_text
from app.assistant_conversation_patch import _extract_command_after_wake


class AssistantToolTests(unittest.TestCase):
    def test_normalizes_portuguese_text(self):
        self.assertEqual(normalize_text("Quem está aqui?"), "quem esta aqui")

    def test_detects_basic_questions(self):
        self.assertEqual(detect_intent("Quem sou eu?")[0], "who_am_i")
        self.assertEqual(detect_intent("Quem está aqui?")[0], "who_is_here")
        self.assertEqual(detect_intent("Quem passou aqui hoje?")[0], "who_today")
        self.assertEqual(detect_intent("Quantas pessoas passaram hoje?")[0], "count_today")
        self.assertEqual(detect_intent("Tem alguém desconhecido?")[0], "unknown_today")
        self.assertEqual(detect_intent("Que horas são?")[0], "time")

    def test_detects_whisper_time_variants(self):
        variants = [
            "Que hora são?",
            "Que horas?",
            "Que horas são agora?",
            "Qual horário?",
            "Horário agora",
            "Me fala a hora",
            "Horas agora",
        ]
        for phrase in variants:
            with self.subTest(phrase=phrase):
                self.assertEqual(detect_intent(phrase)[0], "time")

    def test_detects_last_seen_named_person(self):
        intent, name = detect_intent(
            "Quando Andressa passou por aqui?",
            ["Miquéias", "Andressa"],
        )
        self.assertEqual(intent, "last_seen")
        self.assertEqual(name, "Andressa")

    def test_extracts_command_after_wake_phrase(self):
        self.assertEqual(
            _extract_command_after_wake("Oi, Tonho, quem passou aqui hoje?"),
            "quem passou aqui hoje",
        )
        self.assertEqual(_extract_command_after_wake("Oi Tonio! Quem sou eu?"), "quem sou eu")
        self.assertEqual(_extract_command_after_wake("Oi, Tonho, que hora são?"), "que hora sao")
        self.assertEqual(_extract_command_after_wake("Oi, Tonho!"), "")


if __name__ == "__main__":
    unittest.main()

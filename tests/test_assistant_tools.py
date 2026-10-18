import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.assistant_tools import detect_intent, normalize_text
from app.assistant_conversation_patch import _extract_command_after_wake
from app.assistant_v452_patch import _merge_partial_command, looks_like_time_request
from app.assistant_command_stt_patch import _eligible_for_wake_probe, _merge_wake_and_command
from app.assistant_model_settings_patch import _validate_model
from app.config import (
    WAKE_COMMAND_WHISPER_MODEL,
    WAKE_WHISPER_MODEL,
    WHISPER_COMMAND_MODELS,
    WHISPER_WAKE_MODELS,
)


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

    def test_history_does_not_require_word_hoje(self):
        self.assertEqual(detect_intent("Quem passou por aqui?")[0], "who_today")
        self.assertEqual(detect_intent("Quem apareceu aqui?")[0], "who_today")
        self.assertEqual(detect_intent("Quantas pessoas passaram por aqui?")[0], "count_today")

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

    def test_split_windows_do_not_duplicate_boundary_word(self):
        self.assertEqual(_merge_partial_command("quem", "Quem passou por aqui?"), "quem passou por aqui")
        self.assertEqual(_merge_partial_command("que", "horas são?"), "que horas sao")
        self.assertEqual(_merge_partial_command("quem passou", "passou por aqui"), "quem passou por aqui")

    def test_v452_raw_time_fast_path(self):
        variants = [
            "Oi, Tonho, que horas são?",
            "Oi Tonio que hora são",
            "Oi Tonho qual o horário",
            "Oi Tonho que oras são",
            "Que horas são",
        ]
        for phrase in variants:
            with self.subTest(phrase=phrase):
                self.assertTrue(looks_like_time_request(phrase))
        self.assertFalse(looks_like_time_request("Oi, Tonho, quem está aqui?"))

    def test_split_time_question_can_be_recombined(self):
        self.assertFalse(looks_like_time_request("Oi Tonho que"))
        self.assertTrue(looks_like_time_request("que horas são"))

    def test_dual_stt_preserves_wake_from_fast_model(self):
        merged = _merge_wake_and_command(
            "Oi, Tonho! Queria, Tonho!",
            "Que horas são?",
        )
        self.assertTrue(merged.startswith("Oi, Tonho!"))
        self.assertIn("Que horas são?", merged)
        self.assertTrue(looks_like_time_request(merged))

    def test_dual_stt_keeps_command_wake_when_stronger_model_hears_it(self):
        merged = _merge_wake_and_command(
            "Oi Tonho",
            "Oi, Tonho, quem está aqui?",
        )
        self.assertEqual(merged, "Oi, Tonho, quem está aqui?")

    def test_wake_rescue_accepts_observed_fast_model_mishearing(self):
        self.assertTrue(_eligible_for_wake_probe("Oito em André-tapasso Brací.", 0.00905))

    def test_wake_rescue_rejects_low_energy_or_long_speech(self):
        self.assertFalse(_eligible_for_wake_probe("Oito em André-tapasso Brací.", 0.001))
        self.assertFalse(
            _eligible_for_wake_probe(
                "esta é uma conversa longa que não deveria acionar a segunda checagem continuamente",
                0.02,
            )
        )

    def test_v47_model_defaults_and_choices(self):
        self.assertEqual(WAKE_WHISPER_MODEL, "base")
        self.assertEqual(WAKE_COMMAND_WHISPER_MODEL, "small")
        self.assertEqual(WHISPER_WAKE_MODELS, ("tiny", "base", "small"))
        self.assertIn("medium", WHISPER_COMMAND_MODELS)

    def test_model_validation(self):
        self.assertEqual(_validate_model("BASE", WHISPER_WAKE_MODELS, "base"), "base")
        self.assertEqual(_validate_model(None, WHISPER_COMMAND_MODELS, "small"), "small")
        with self.assertRaises(ValueError):
            _validate_model("large-v3", WHISPER_WAKE_MODELS, "base")


if __name__ == "__main__":
    unittest.main()

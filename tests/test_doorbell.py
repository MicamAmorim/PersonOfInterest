import unittest

from backend.app.doorbell import _clean_name
from backend.app.doorbell_patch import _looks_like_arrival_notice


class DoorbellIntentTests(unittest.TestCase):
    def test_arrival_notice_phrases(self):
        self.assertTrue(_looks_like_arrival_notice("avise que eu estou na porta"))
        self.assertTrue(_looks_like_arrival_notice("avisa que eu tô na porta"))
        self.assertTrue(_looks_like_arrival_notice("avise que eu cheguei"))
        self.assertTrue(_looks_like_arrival_notice("avisa por favor que cheguei"))

    def test_unrelated_commands_do_not_match(self):
        self.assertFalse(_looks_like_arrival_notice("pesquise na internet quem chegou"))
        self.assertFalse(_looks_like_arrival_notice("quem está na porta"))
        self.assertFalse(_looks_like_arrival_notice("avise quando alguém chegar"))

    def test_local_name_is_normalized_and_bounded(self):
        self.assertEqual(_clean_name("  Miquéias   Amorim  "), "Miquéias Amorim")
        self.assertLessEqual(len(_clean_name("x" * 200)), 80)


if __name__ == "__main__":
    unittest.main()

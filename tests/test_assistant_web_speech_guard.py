import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import assistant_conversation_patch as conversation
from app import assistant_tools as tools
from app import assistant_web_search_patch as web
from app.assistant import manager as assistant_manager


class AssistantWebSpeechGuardTests(unittest.TestCase):
    def test_generic_web_answer_is_silent(self):
        fake = [
            web.WebResult(
                "Torre Eiffel",
                "A Torre Eiffel tem aproximadamente 330 metros de altura.",
                "https://www.toureiffel.paris/",
            )
        ]
        with patch.object(web, "_search", return_value=(fake, "searxng")), patch.object(
            assistant_manager, "speak"
        ) as speak:
            answer = tools.answer_command(
                2,
                "pesquise na internet para mim qual a altura da torre eiffel",
                "America/Bahia",
            )
        self.assertEqual(answer.intent, "web_search")
        self.assertIn("330 metros", answer.text)
        speak.assert_not_called()

    def test_live_conversation_may_speak_search_preface(self):
        fake = [
            web.WebResult(
                "Torre Eiffel",
                "A Torre Eiffel tem aproximadamente 330 metros de altura.",
                "https://www.toureiffel.paris/",
            )
        ]
        with patch.object(web, "_search", return_value=(fake, "searxng")), patch.object(
            assistant_manager, "settings_for", return_value={"voice_gender": "male"}
        ), patch.object(assistant_manager, "speak") as speak:
            answer = conversation.answer_command(
                2,
                "pesquise na internet para mim qual a altura da torre eiffel",
                "America/Bahia",
            )
        self.assertEqual(answer.intent, "web_search")
        speak.assert_called_once_with(2, web.WEB_SEARCH_PREFACE, voice_gender="male")


if __name__ == "__main__":
    unittest.main()

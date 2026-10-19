import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import assistant_tools as tools
from app.assistant_web_search_patch import (
    WebResult,
    _DuckParser,
    _extract_web_query,
    _parse_searxng_payload,
    _summarize,
)


class AssistantWebSearchTests(unittest.TestCase):
    def test_extracts_internet_search_query(self):
        self.assertEqual(
            _extract_web_query("Pesquise na internet: qual é a altura da Torre Eiffel?"),
            "qual é a altura da Torre Eiffel",
        )
        self.assertEqual(
            _extract_web_query("pesquisa no google altura torre eiffel"),
            "altura torre eiffel",
        )

    def test_web_search_intent_is_installed(self):
        intent, argument = tools.detect_intent("Pesquise na internet quem criou o Python")
        self.assertEqual(intent, "web_search")
        self.assertEqual(argument, "quem criou o Python")

    def test_date_intents_are_installed(self):
        self.assertEqual(tools.detect_intent("Que dia é hoje?")[0], "date")
        self.assertEqual(tools.detect_intent("Qual a data e hora?")[0], "date_time")
        self.assertEqual(tools.detect_intent("Que horas são?")[0], "time")

    def test_searxng_json_is_converted_to_results(self):
        results = _parse_searxng_payload(
            {
                "results": [
                    {
                        "title": "Torre Eiffel",
                        "content": "A Torre Eiffel tem aproximadamente 330 metros de altura.",
                        "url": "https://www.toureiffel.paris/",
                    },
                    {
                        "title": "Eiffel Tower",
                        "content": "A estrutura fica em Paris, na França.",
                        "url": "https://en.wikipedia.org/wiki/Eiffel_Tower",
                    },
                ]
            }
        )
        self.assertEqual(len(results), 2)
        self.assertIn("330 metros", results[0].snippet)
        self.assertEqual(results[0].url, "https://www.toureiffel.paris/")

    def test_summary_uses_search_snippets_and_sources(self):
        text = _summarize(
            "altura torre eiffel",
            [
                WebResult("Torre Eiffel", "A Torre Eiffel tem aproximadamente 330 metros de altura.", "https://www.toureiffel.paris/"),
                WebResult("Eiffel Tower", "A estrutura fica em Paris, na França.", "https://en.wikipedia.org/wiki/Eiffel_Tower"),
            ],
        )
        self.assertIn("330 metros", text)
        self.assertIn("toureiffel.paris", text)

    def test_duckduckgo_parser_collects_title_and_snippet(self):
        parser = _DuckParser()
        parser.feed(
            '<a class="result__a" href="https://example.com">Exemplo</a>'
            '<a class="result__snippet">Uma resposta de exemplo para a busca.</a>'
        )
        self.assertEqual(len(parser.results), 1)
        self.assertEqual(parser.results[0].title, "Exemplo")
        self.assertIn("resposta de exemplo", parser.results[0].snippet)


if __name__ == "__main__":
    unittest.main()

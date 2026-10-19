from __future__ import annotations

import json
import urllib.parse
from typing import Any

from . import assistant_web_search_patch as web


WIKIPEDIA_API = "https://pt.wikipedia.org/w/api.php"


def _wiki_request(params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    payload = json.loads(web._request(f"{WIKIPEDIA_API}?{query}").decode("utf-8", errors="replace"))
    return payload if isinstance(payload, dict) else {}


def _wikipedia_search(query: str) -> list[web.WebResult]:
    search = _wiki_request(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 3,
            "srprop": "snippet",
            "format": "json",
            "utf8": "1",
        }
    )
    rows = ((search.get("query") or {}).get("search") or []) if isinstance(search, dict) else []
    results: list[web.WebResult] = []

    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        detail = _wiki_request(
            {
                "action": "query",
                "prop": "extracts",
                "exintro": "1",
                "explaintext": "1",
                "exchars": "1200",
                "redirects": "1",
                "titles": title,
                "format": "json",
                "utf8": "1",
            }
        )
        pages = ((detail.get("query") or {}).get("pages") or {}) if isinstance(detail, dict) else {}
        extract = ""
        if isinstance(pages, dict):
            for page in pages.values():
                if isinstance(page, dict):
                    extract = web._clean_text(str(page.get("extract") or ""))
                    if extract:
                        break
        if not extract:
            extract = web._clean_text(str(row.get("snippet") or ""))
        if not extract:
            continue
        url = "https://pt.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="_()'-")
        results.append(web.WebResult(title=title, snippet=extract, url=url))

    return results


def install() -> None:
    if getattr(web, "_poi_wikipedia_fallback_installed", False):
        return

    original_search = web._search

    def search_with_wikipedia(query: str) -> tuple[list[web.WebResult], str]:
        original_error: Exception | None = None
        try:
            results, provider = original_search(query)
            if results:
                return results, provider
        except Exception as exc:
            original_error = exc
            provider = "web"

        try:
            results = _wikipedia_search(query)
            if results:
                return results, "wikipedia"
        except Exception:
            pass

        if original_error is not None:
            raise original_error
        return [], provider

    web._search = search_with_wikipedia
    web._poi_wikipedia_fallback_installed = True

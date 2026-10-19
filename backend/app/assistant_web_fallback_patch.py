from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

from . import assistant_web_search_patch as web


WIKIPEDIA_API = "https://pt.wikipedia.org/w/api.php"


def _wiki_request(params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    payload = json.loads(web._request(f"{WIKIPEDIA_API}?{query}").decode("utf-8", errors="replace"))
    return payload if isinstance(payload, dict) else {}


def _wiki_query_candidates(query: str) -> list[str]:
    """Prefer the encyclopedic subject over conversational question filler."""
    original = re.sub(r"\s+", " ", str(query or "")).strip(" .?!:;,-")
    if not original:
        return []

    subject = original
    patterns = (
        # "qual a altura da Torre Eiffel" -> "Torre Eiffel"
        r"^(?:qual|quais)\s+(?:(?:e|eh|sao)\s+)?(?:a|o|as|os\s+)?(?:altura|idade|capital|populacao|população|tamanho|comprimento|largura|peso|fundador|autor|criador)\s+(?:da|do|de|das|dos)\s+",
        # "o que é um anfíbio" -> "anfíbio"
        r"^(?:o\s+que|oque)\s+(?:e|eh)\s+(?:(?:um|uma|o|a)\s+)?",
        r"^(?:o\s+que|oque)\s+significa\s+",
        r"^(?:quem)\s+(?:e|eh|foi)\s+(?:(?:o|a)\s+)?",
        r"^(?:defina|explique)\s+(?:(?:o\s+que|oque)\s+(?:e|eh)\s+)?",
    )
    for pattern in patterns:
        candidate = re.sub(pattern, "", subject, count=1, flags=re.IGNORECASE).strip(" .?!:;,-")
        if candidate != subject and candidate:
            subject = candidate
            break

    candidates: list[str] = []
    for value in (subject, original):
        value = re.sub(r"\s+", " ", value).strip()
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def _row_relevance(query: str, row: dict[str, Any]) -> float:
    q_tokens = {
        token for token in web.tools.normalize_text(query).split()
        if len(token) >= 3 and token not in {"que", "qual", "quem", "uma", "uns", "das", "dos", "para", "mim"}
    }
    title = web.tools.normalize_text(str(row.get("title") or ""))
    snippet = web.tools.normalize_text(str(row.get("snippet") or ""))
    if not q_tokens:
        return 0.0
    title_tokens = set(title.split())
    snippet_tokens = set(snippet.split())
    title_hits = len(q_tokens & title_tokens)
    snippet_hits = len(q_tokens & snippet_tokens)
    exact_bonus = 2.5 if web.tools.normalize_text(query) == title else 0.0
    return exact_bonus + title_hits * 2.0 + snippet_hits * 0.35


def _fetch_article(row: dict[str, Any]) -> web.WebResult | None:
    title = str(row.get("title") or "").strip()
    if not title:
        return None
    detail = _wiki_request(
        {
            "action": "query",
            "prop": "extracts",
            "exintro": "1",
            "explaintext": "1",
            "exchars": "1400",
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
        return None
    url = "https://pt.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="_()'-")
    return web.WebResult(title=title, snippet=extract, url=url)


def _wikipedia_search(query: str) -> list[web.WebResult]:
    # Wikipedia is a last-resort factual fallback. One strong article is safer
    # than concatenating the intros of three unrelated search hits.
    for candidate in _wiki_query_candidates(query):
        search = _wiki_request(
            {
                "action": "query",
                "list": "search",
                "srsearch": candidate,
                "srlimit": 5,
                "srprop": "snippet",
                "format": "json",
                "utf8": "1",
            }
        )
        rows = ((search.get("query") or {}).get("search") or []) if isinstance(search, dict) else []
        rows = [row for row in rows if isinstance(row, dict) and row.get("title")]
        if not rows:
            continue
        rows.sort(key=lambda row: _row_relevance(candidate, row), reverse=True)
        for row in rows[:3]:
            result = _fetch_article(row)
            if result is not None:
                return [result]
    return []


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

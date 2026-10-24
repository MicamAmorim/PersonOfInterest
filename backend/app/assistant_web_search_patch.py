from __future__ import annotations

import html
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from . import assistant_tools as tools
from . import wake_word as ww


WEB_SEARCH_PREFACE = "Certo, espera um momento, vou pesquisar."
WEB_SEARCH_TIMEOUT = max(2.0, min(20.0, float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "8"))))
WEB_SEARCH_RESULTS = max(2, min(8, int(os.getenv("WEB_SEARCH_RESULT_COUNT", "5"))))
SEARXNG_URL = os.getenv("SEARXNG_URL", "").strip().rstrip("/")
SEARXNG_LOCAL_URL = os.getenv("SEARXNG_LOCAL_URL", "http://127.0.0.1:8888").strip().rstrip("/")
SEARXNG_PROBE_TIMEOUT = max(0.25, min(2.0, float(os.getenv("SEARXNG_PROBE_TIMEOUT_SECONDS", "0.75"))))


@dataclass(slots=True)
class WebResult:
    title: str
    snippet: str
    url: str


def _looks_like_date_question(q: str) -> bool:
    return any(
        phrase in q
        for phrase in (
            "que dia e hoje",
            "que dia eh hoje",
            "qual dia e hoje",
            "qual dia eh hoje",
            "qual a data",
            "qual e a data",
            "qual eh a data",
            "data de hoje",
            "dia de hoje",
            "que data e hoje",
            "que data eh hoje",
        )
    )


def _looks_like_date_time_question(q: str) -> bool:
    has_date = _looks_like_date_question(q) or "data e hora" in q or "dia e hora" in q
    has_time = tools._looks_like_time_question(q) or "data e hora" in q or "dia e hora" in q
    return has_date and has_time


def _cleanup_spoken_query(query: str) -> str:
    value = query.strip(" .?!:;,-")
    value = re.sub(r"^\s*(?:para\s+mim|por\s+favor)\s*[,;:\-]?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _extract_web_query(text: str) -> str | None:
    value = (text or "").strip()
    if not value:
        return None
    patterns = (
        r"^\s*(?:pesquise|pesquisa|pesquisar|procure|procurar|busque|buscar)\s+(?:na\s+internet|na\s+web|no\s+google)\s*[:;,\-]?\s*(.+?)\s*$",
        r"^\s*(?:pesquise|pesquisa|pesquisar|procure|procurar|busque|buscar)\s*[:;,\-]\s*(.+?)\s*$",
    )
    for pattern in patterns:
        match = re.match(pattern, value, flags=re.IGNORECASE)
        if match:
            query = _cleanup_spoken_query(match.group(1))
            return query or None
    return None


def _format_date(timezone_name: str | None, include_time: bool = False) -> str:
    now = tools._local_now(timezone_name)
    weekdays = (
        "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo",
    )
    months = (
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    )
    text = f"Hoje é {weekdays[now.weekday()]}, {now.day} de {months[now.month - 1]} de {now.year}."
    if include_time:
        text += f" Agora são {now.strftime('%H:%M')}."
    return text


def _clean_text(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return " ".join(value.split())


def _request(url: str, *, timeout: float | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PersonOfInterest-Tonho/0.5 (+local assistant)",
            "Accept": "application/json,text/html;q=0.8,*/*;q=0.5",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout or WEB_SEARCH_TIMEOUT) as response:
        return response.read(1_500_000)


def _parse_searxng_payload(payload: dict[str, Any]) -> list[WebResult]:
    output: list[WebResult] = []

    for answer in payload.get("answers") or []:
        if isinstance(answer, str):
            snippet = _clean_text(answer)
        elif isinstance(answer, dict):
            snippet = _clean_text(str(answer.get("answer") or answer.get("content") or answer.get("title") or ""))
        else:
            snippet = ""
        if snippet:
            output.append(WebResult(title="Resposta direta", snippet=snippet, url=""))

    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = _clean_text(str(item.get("title") or ""))
        snippet = _clean_text(str(item.get("content") or item.get("snippet") or ""))
        url = str(item.get("url") or "").strip()
        if title or snippet:
            output.append(WebResult(title=title, snippet=snippet, url=url))
        if len(output) >= WEB_SEARCH_RESULTS:
            break

    if len(output) < WEB_SEARCH_RESULTS:
        for item in payload.get("infoboxes") or []:
            if not isinstance(item, dict):
                continue
            title = _clean_text(str(item.get("infobox") or item.get("title") or ""))
            snippet = _clean_text(str(item.get("content") or ""))
            urls = item.get("urls") or []
            url = ""
            if urls and isinstance(urls[0], dict):
                url = str(urls[0].get("url") or "")
            if title or snippet:
                output.append(WebResult(title=title, snippet=snippet, url=url))
            if len(output) >= WEB_SEARCH_RESULTS:
                break

    return output[:WEB_SEARCH_RESULTS]


def _alternative_queries(payload: dict[str, Any]) -> list[str]:
    alternatives: list[str] = []
    for field, key in (("corrections", "correction"), ("suggestions", "suggestion")):
        for item in payload.get(field) or []:
            if isinstance(item, str):
                candidate = item
            elif isinstance(item, dict):
                candidate = str(item.get(key) or item.get("title") or "")
            else:
                candidate = ""
            candidate = _cleanup_spoken_query(candidate)
            if candidate and candidate not in alternatives:
                alternatives.append(candidate)
    return alternatives[:3]


def _searxng_payload(base_url: str, query: str) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "json",
            "language": "pt-BR",
            "safesearch": "1",
            "categories": "general",
        }
    )
    payload = json.loads(
        _request(f"{base_url}/search?{params}").decode("utf-8", errors="replace")
    )
    return payload if isinstance(payload, dict) else {}


def _candidate_searxng_urls() -> list[str]:
    urls: list[str] = []
    for value in (SEARXNG_URL, SEARXNG_LOCAL_URL):
        clean = (value or "").strip().rstrip("/")
        if clean and clean not in urls:
            urls.append(clean)
    return urls


def _searxng_reachable(base_url: str) -> bool:
    try:
        _request(f"{base_url}/config", timeout=SEARXNG_PROBE_TIMEOUT)
        return True
    except Exception:
        return False


def _searxng_search(query: str) -> tuple[list[WebResult], str | None]:
    last_error: Exception | None = None
    for base_url in _candidate_searxng_urls():
        if not _searxng_reachable(base_url):
            continue
        try:
            payload = _searxng_payload(base_url, query)
            results = _parse_searxng_payload(payload)
            if results:
                return results, base_url

            for alternative in _alternative_queries(payload):
                if tools.normalize_text(alternative) == tools.normalize_text(query):
                    continue
                retry_payload = _searxng_payload(base_url, alternative)
                results = _parse_searxng_payload(retry_payload)
                if results:
                    return results, base_url
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return [], None


class _DuckParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[WebResult] = []
        self._mode: str | None = None
        self._buffer: list[str] = []
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key: value or "" for key, value in attrs}
        classes = set(data.get("class", "").split())
        if tag == "a" and ({"result__a", "result-link"} & classes):
            self._mode = "title"
            self._buffer = []
            self._href = data.get("href", "")
        elif ({"result__snippet", "result-snippet"} & classes):
            self._mode = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._mode:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._mode == "title" and tag == "a":
            title = _clean_text(" ".join(self._buffer))
            if title:
                self.results.append(WebResult(title=title, snippet="", url=self._href))
            self._mode = None
            self._buffer = []
            self._href = ""
        elif self._mode == "snippet" and tag in {"a", "div", "td"}:
            snippet = _clean_text(" ".join(self._buffer))
            if snippet and self.results:
                self.results[-1].snippet = snippet
            self._mode = None
            self._buffer = []


def _duckduckgo_instant(query: str) -> list[WebResult]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
            "no_redirect": "1",
        }
    )
    payload = json.loads(_request(f"https://api.duckduckgo.com/?{params}").decode("utf-8", errors="replace"))
    output: list[WebResult] = []
    abstract = _clean_text(str(payload.get("AbstractText") or "")) if isinstance(payload, dict) else ""
    if abstract:
        output.append(
            WebResult(
                title=_clean_text(str(payload.get("Heading") or "Resposta")),
                snippet=abstract,
                url=str(payload.get("AbstractURL") or ""),
            )
        )
    return output


def _duckduckgo_search(query: str) -> list[WebResult]:
    try:
        instant = _duckduckgo_instant(query)
        if instant:
            return instant[:WEB_SEARCH_RESULTS]
    except Exception:
        pass

    encoded = urllib.parse.urlencode({"q": query, "kl": "br-pt"})
    parser = _DuckParser()
    parser.feed(_request(f"https://html.duckduckgo.com/html/?{encoded}").decode("utf-8", errors="replace"))
    return parser.results[:WEB_SEARCH_RESULTS]


def _provider() -> str:
    return "searxng" if _candidate_searxng_urls() else "duckduckgo"


def _search(query: str) -> tuple[list[WebResult], str]:
    searxng_error: Exception | None = None
    try:
        results, base_url = _searxng_search(query)
        if results and base_url:
            return results, "searxng"
    except Exception as exc:
        searxng_error = exc

    try:
        results = _duckduckgo_search(query)
        if results:
            return results, "duckduckgo"
    except Exception:
        if searxng_error:
            raise searxng_error
        raise

    if searxng_error:
        raise searxng_error
    return [], "duckduckgo"


def _domain_label(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        return host or "web"
    except Exception:
        return "web"


def _summarize(query: str, results: list[WebResult]) -> str:
    if not results:
        return "Não encontrei resultados úteis para essa pesquisa."
    candidates: list[str] = []
    seen: set[str] = set()
    for result in results:
        text = _clean_text(result.snippet)
        if not text:
            continue
        pieces = re.split(r"(?<=[.!?])\s+", text)
        for piece in pieces:
            piece = piece.strip()
            key = tools.normalize_text(piece)
            if len(piece) < 20 or key in seen:
                continue
            seen.add(key)
            candidates.append(piece)
            break
        if len(candidates) >= 3:
            break
    if not candidates:
        candidates = [result.title for result in results[:2] if result.title]
    summary = " ".join(candidates[:3]).strip()
    if len(summary) > 620:
        summary = summary[:617].rsplit(" ", 1)[0] + "..."
    sources: list[str] = []
    for result in results:
        label = _domain_label(result.url)
        if label != "web" and label not in sources:
            sources.append(label)
        if len(sources) >= 3:
            break
    suffix = f" Fontes: {', '.join(sources)}." if sources else ""
    return f"Encontrei o seguinte: {summary}{suffix}"


def _speak_preface(camera_id: int) -> None:
    try:
        from .assistant import manager as assistant_manager
        settings = assistant_manager.settings_for(camera_id)
        assistant_manager.speak(
            camera_id,
            WEB_SEARCH_PREFACE,
            voice_gender=str(settings.get("voice_gender") or "female"),
        )
    except Exception:
        return


def install() -> None:
    if getattr(tools, "_poi_web_search_installed", False):
        return

    original_detect = tools.detect_intent
    original_answer = tools.answer_command

    def detect(text: str, person_names: list[str] | None = None) -> tuple[str, str | None]:
        query = _extract_web_query(text)
        if query:
            return "web_search", query
        q = tools.normalize_text(text)
        if _looks_like_date_time_question(q):
            return "date_time", None
        if _looks_like_date_question(q):
            return "date", None
        return original_detect(text, person_names)

    def answer(camera_id: int, text: str, timezone_name: str | None = None) -> Any:
        intent, argument = detect(text, tools._person_names())
        if intent == "date":
            return tools.CommandAnswer(_format_date(timezone_name), intent)
        if intent == "date_time":
            return tools.CommandAnswer(_format_date(timezone_name, include_time=True), intent)
        if intent == "web_search":
            query = str(argument or "").strip()
            if not query:
                return tools.CommandAnswer("Diga o que você quer que eu pesquise.", intent, "unknown")
            _speak_preface(camera_id)
            try:
                results, provider = _search(query)
                return tools.CommandAnswer(_summarize(query, results), intent, f"web:{provider}")
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout) as exc:
                return tools.CommandAnswer(f"Não consegui acessar a pesquisa na internet agora. {type(exc).__name__}.", intent, "web:error")
            except Exception:
                return tools.CommandAnswer("Não consegui concluir essa pesquisa na internet.", intent, "web:error")
        return original_answer(camera_id, text, timezone_name)

    tools.detect_intent = detect
    tools.answer_command = answer
    tools._poi_web_search_installed = True

    from . import assistant_conversation_patch as conversation
    conversation.answer_command = tools.answer_command

    original_state = ww.WakeWordManager.state

    def state_with_web(self: Any) -> dict[str, Any]:
        data = original_state(self)
        commands = list(data.get("simple_commands") or [])
        for command in ("Que dia é hoje?", "Qual a data e hora?", "Pesquise na internet: qual é a altura da Torre Eiffel?"):
            if command not in commands:
                commands.append(command)
        data["simple_commands"] = commands
        data["web_search"] = {
            "enabled": True,
            "provider": _provider(),
            "searxng_configured": bool(SEARXNG_URL),
            "searxng_autodiscovery": SEARXNG_LOCAL_URL or None,
            "searxng_candidates": _candidate_searxng_urls(),
            "fallback": "duckduckgo",
            "timeout_seconds": WEB_SEARCH_TIMEOUT,
            "result_count": WEB_SEARCH_RESULTS,
        }
        return data

    ww.WakeWordManager.state = state_with_web

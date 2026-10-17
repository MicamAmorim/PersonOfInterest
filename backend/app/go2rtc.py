from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .config import GO2RTC_API_URL


@dataclass(slots=True)
class Go2RTCResult:
    ok: bool
    error: str | None = None


def _request(method: str, path: str, params: dict[str, str] | None = None, timeout: float = 5.0) -> bytes:
    query = urllib.parse.urlencode(params or {})
    url = f"{GO2RTC_API_URL}{path}"
    if query:
        url += f"?{query}"
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def health() -> Go2RTCResult:
    try:
        raw = _request("GET", "/api/streams", timeout=2.0)
        json.loads(raw or b"{}")
        return Go2RTCResult(ok=True)
    except Exception as exc:  # network boundary
        return Go2RTCResult(ok=False, error=str(exc))


def upsert_stream(stream_name: str, rtsp_url: str) -> Go2RTCResult:
    try:
        # PUT persists the stream in go2rtc's config and updates the running process.
        _request("PUT", "/api/streams", {"name": stream_name, "src": rtsp_url})
        return Go2RTCResult(ok=True)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip() or str(exc)
        return Go2RTCResult(ok=False, error=detail)
    except Exception as exc:
        return Go2RTCResult(ok=False, error=str(exc))


def delete_stream(stream_name: str) -> Go2RTCResult:
    try:
        _request("DELETE", "/api/streams", {"src": stream_name})
        return Go2RTCResult(ok=True)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip() or str(exc)
        return Go2RTCResult(ok=False, error=detail)
    except Exception as exc:
        return Go2RTCResult(ok=False, error=str(exc))

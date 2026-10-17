from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Sequence

from .config import GO2RTC_API_URL


@dataclass(slots=True)
class Go2RTCResult:
    ok: bool
    error: str | None = None


QueryValue = str | Sequence[str]


def _request(
    method: str,
    path: str,
    params: Mapping[str, QueryValue] | None = None,
    timeout: float = 5.0,
) -> bytes:
    query = urllib.parse.urlencode(params or {}, doseq=True)
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


def stream_info(stream_name: str) -> dict:
    raw = _request("GET", "/api/streams", {"src": stream_name}, timeout=2.5)
    payload = json.loads(raw or b"{}")
    return payload if isinstance(payload, dict) else {}


def _stream_exists(stream_name: str) -> bool:
    try:
        stream_info(stream_name)
        return True
    except Exception:
        return False


def dvrip_backchannel_url(rtsp_url: str) -> str | None:
    """Build an iCSee/XMEye DVRIP audio backchannel source when credentials exist.

    go2rtc can combine the regular RTSP source (video + camera microphone) with
    a DVRIP source dedicated to microphone -> camera speaker. The DVRIP source
    is lazy, so non-DVRIP cameras keep working even if the extra source is never
    usable; browser talkback simply won't negotiate on those cameras.
    """
    try:
        parsed = urllib.parse.urlsplit(rtsp_url)
        if not parsed.hostname or parsed.username is None:
            return None
        username = urllib.parse.quote(urllib.parse.unquote(parsed.username), safe="")
        password_raw = urllib.parse.unquote(parsed.password or "")
        password = urllib.parse.quote(password_raw, safe="")
        auth = f"{username}:{password}@"
        return f"dvrip://{auth}{parsed.hostname}:34567?backchannel=1"
    except Exception:
        return None


def upsert_stream(
    stream_name: str,
    rtsp_url: str,
    extra_sources: Sequence[str] | None = None,
) -> Go2RTCResult:
    sources = [rtsp_url]
    for source in extra_sources or ():
        if source and source not in sources:
            sources.append(source)
    try:
        _request("PUT", "/api/streams", {"name": stream_name, "src": sources})
        return Go2RTCResult(ok=True)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip() or str(exc)
        # go2rtc creates/updates the in-memory stream before trying to patch its YAML.
        # PersonOfInterest persists camera configuration in SQLite, so a YAML-patch
        # failure is harmless as long as the runtime stream actually exists.
        if _stream_exists(stream_name):
            return Go2RTCResult(ok=True)
        return Go2RTCResult(ok=False, error=detail)
    except Exception as exc:
        return Go2RTCResult(ok=False, error=str(exc))


def delete_stream(stream_name: str) -> Go2RTCResult:
    try:
        _request("DELETE", "/api/streams", {"src": stream_name})
        return Go2RTCResult(ok=True)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip() or str(exc)
        # If it is already gone from runtime, consider deletion successful.
        if not _stream_exists(stream_name):
            return Go2RTCResult(ok=True)
        return Go2RTCResult(ok=False, error=detail)
    except Exception as exc:
        return Go2RTCResult(ok=False, error=str(exc))

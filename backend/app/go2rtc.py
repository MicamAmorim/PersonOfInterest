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
    effective_url: str | None = None
    warning: str | None = None


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


def _drop_stream_quietly(stream_name: str) -> None:
    try:
        _request("DELETE", "/api/streams", {"src": stream_name}, timeout=2.0)
    except Exception:
        pass


def talkback_stream_name(stream_name: str) -> str:
    return f"{stream_name}_talkback"


def local_restream_url(stream_name: str) -> str:
    return f"rtsp://127.0.0.1:8554/{urllib.parse.quote(stream_name, safe='')}"


def dvrip_backchannel_url(rtsp_url: str) -> str | None:
    """Build an iCSee/XMEye DVRIP audio backchannel source when credentials exist.

    RTSP credentials are not guaranteed to be accepted by DVRIP on every iCSee
    firmware, so DVRIP is deliberately isolated from the primary video stream.
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
    """Create/update a go2rtc stream without second-guessing camera RTSP auth.

    go2rtc is the production RTSP client used by the application and supports a
    wider range of camera-specific RTSP/Digest quirks than PersonOfInterest's
    lightweight discovery probe. A custom preflight must therefore never block
    a camera that go2rtc itself may be able to open.

    Optional DVRIP sources are accepted only on the dedicated *_talkback stream
    so talkback authentication failures cannot poison normal video/vision.
    """
    is_talkback = stream_name.endswith("_talkback")
    sources = [rtsp_url]
    if is_talkback:
        for source in extra_sources or ():
            if source and source not in sources:
                sources.append(source)

    try:
        _request("PUT", "/api/streams", {"name": stream_name, "src": sources})
        return Go2RTCResult(ok=True, effective_url=rtsp_url)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip() or str(exc)
        # go2rtc may have already created the in-memory stream even when writing
        # its temporary YAML fails. PersonOfInterest persists camera config in
        # SQLite, so an existing runtime stream is sufficient here.
        if _stream_exists(stream_name):
            return Go2RTCResult(ok=True, effective_url=rtsp_url)
        return Go2RTCResult(ok=False, error=detail)
    except Exception as exc:
        return Go2RTCResult(ok=False, error=str(exc))


def configure_talkback_stream(stream_name: str, rtsp_url: str) -> Go2RTCResult:
    """Create/update a lazy stream used only while the user is talking."""
    backchannel = dvrip_backchannel_url(rtsp_url)
    if not backchannel:
        return Go2RTCResult(ok=False, error="DVRIP backchannel sem credenciais")
    return upsert_stream(
        talkback_stream_name(stream_name),
        local_restream_url(stream_name),
        [backchannel],
    )


def delete_stream(stream_name: str) -> Go2RTCResult:
    if not stream_name.endswith("_talkback"):
        _drop_stream_quietly(talkback_stream_name(stream_name))
    try:
        _request("DELETE", "/api/streams", {"src": stream_name})
        return Go2RTCResult(ok=True)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip() or str(exc)
        if not _stream_exists(stream_name):
            return Go2RTCResult(ok=True)
        return Go2RTCResult(ok=False, error=detail)
    except Exception as exc:
        return Go2RTCResult(ok=False, error=str(exc))

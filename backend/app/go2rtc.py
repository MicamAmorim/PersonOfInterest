from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Sequence

from . import discovery
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


def _anonymous_rtsp_url(rtsp_url: str) -> str | None:
    """Return the same RTSP endpoint without userinfo.

    Some inexpensive iCSee/XMEye firmwares expose RTSP anonymously even though
    the mobile app/PTZ interface uses credentials. Supplying userinfo to such a
    firmware can paradoxically be rejected as wrong user/pass. Keep credentials
    in SQLite for PTZ/DVRIP, but allow the video transport itself to be anonymous.
    """
    try:
        parsed = urllib.parse.urlsplit(rtsp_url)
        if parsed.scheme.lower() != "rtsp" or not parsed.hostname:
            return None
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = host
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        return None


def dvrip_backchannel_url(rtsp_url: str) -> str | None:
    """Build an iCSee/XMEye DVRIP audio backchannel source when credentials exist.

    RTSP credentials are not guaranteed to be accepted by DVRIP on every iCSee
    firmware, so this URL is deliberately isolated from the primary stream.
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


def _probe_exact_rtsp(rtsp_url: str) -> Go2RTCResult:
    try:
        parsed = urllib.parse.urlsplit(rtsp_url)
        if parsed.scheme.lower() != "rtsp" or not parsed.hostname:
            return Go2RTCResult(False, "URL RTSP inválida")
        port = int(parsed.port or 554)
        username = urllib.parse.unquote(parsed.username or "")
        password = urllib.parse.unquote(parsed.password or "")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        result = discovery.probe_rtsp(
            parsed.hostname,
            username=username,
            password=password,
            port=port,
            paths=(path,),
        )
        if result.ok:
            return Go2RTCResult(True, effective_url=rtsp_url)
        if result.status_code == 401:
            return Go2RTCResult(False, "RTSP: usuário ou senha recusados pela câmera")
        return Go2RTCResult(False, f"RTSP: {result.error or 'não foi possível abrir o stream'}")
    except Exception as exc:
        return Go2RTCResult(False, f"RTSP: falha ao validar o stream ({exc})")


def _validate_primary_rtsp(rtsp_url: str) -> Go2RTCResult:
    """Validate configured RTSP and transparently try anonymous video fallback."""
    configured = _probe_exact_rtsp(rtsp_url)
    if configured.ok:
        return configured

    try:
        parsed = urllib.parse.urlsplit(rtsp_url)
        has_userinfo = parsed.username is not None or parsed.password is not None
    except Exception:
        has_userinfo = False

    if has_userinfo:
        anonymous_url = _anonymous_rtsp_url(rtsp_url)
        if anonymous_url and anonymous_url != rtsp_url:
            anonymous = _probe_exact_rtsp(anonymous_url)
            if anonymous.ok:
                return Go2RTCResult(
                    True,
                    effective_url=anonymous_url,
                    warning="RTSP de vídeo aceito sem autenticação; credenciais cadastradas foram mantidas para PTZ/talkback.",
                )

    return configured


def upsert_stream(
    stream_name: str,
    rtsp_url: str,
    extra_sources: Sequence[str] | None = None,
) -> Go2RTCResult:
    # Dedicated *_talkback streams are the only streams allowed to use extra
    # DVRIP sources. An optional talkback failure must never poison video.
    is_talkback = stream_name.endswith("_talkback")
    effective_url = rtsp_url
    warning: str | None = None
    if not is_talkback:
        validation = _validate_primary_rtsp(rtsp_url)
        if not validation.ok:
            _drop_stream_quietly(stream_name)
            _drop_stream_quietly(talkback_stream_name(stream_name))
            return validation
        effective_url = validation.effective_url or rtsp_url
        warning = validation.warning

    sources = [effective_url]
    if is_talkback:
        for source in extra_sources or ():
            if source and source not in sources:
                sources.append(source)
    try:
        _request("PUT", "/api/streams", {"name": stream_name, "src": sources})
        return Go2RTCResult(ok=True, effective_url=effective_url, warning=warning)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip() or str(exc)
        if _stream_exists(stream_name):
            return Go2RTCResult(ok=True, effective_url=effective_url, warning=warning)
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

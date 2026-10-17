from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from html import escape
from urllib.parse import urlsplit

from .config import PTZ_ONVIF_PORT


class PTZError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PTZSession:
    host: str
    username: str
    password: str
    profile_token: str
    ptz_url: str


def _credentials(rtsp_url: str) -> tuple[str, str, str]:
    parsed = urlsplit(rtsp_url)
    if not parsed.hostname:
        raise PTZError("URL RTSP sem host")
    return parsed.hostname, parsed.username or "", parsed.password or ""


def _security_header(username: str, password: str) -> str:
    if not username:
        return ""
    nonce = secrets.token_bytes(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    nonce64 = base64.b64encode(nonce).decode()
    return f"""
    <s:Header>
      <wsse:Security s:mustUnderstand="1" xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
        <wsse:UsernameToken>
          <wsse:Username>{escape(username)}</wsse:Username>
          <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</wsse:Password>
          <wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce64}</wsse:Nonce>
          <wsu:Created>{created}</wsu:Created>
        </wsse:UsernameToken>
      </wsse:Security>
    </s:Header>"""


def _envelope(body: str, username: str, password: str) -> bytes:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:tds="http://www.onvif.org/ver10/device/wsdl"
 xmlns:trt="http://www.onvif.org/ver10/media/wsdl"
 xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"
 xmlns:tt="http://www.onvif.org/ver10/schema">
{_security_header(username, password)}
<s:Body>{body}</s:Body>
</s:Envelope>"""
    return xml.encode("utf-8")


def _post(url: str, action: str, body: str, username: str, password: str, timeout: float = 3.5) -> str:
    data = _envelope(body, username, password)
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"'},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise PTZError(f"ONVIF HTTP {exc.code}: {detail[:220]}") from exc
    except Exception as exc:
        raise PTZError(f"Falha ONVIF: {exc}") from exc


def _extract_service(xml: str, service: str) -> str | None:
    pattern = rf"<(?:\w+:)?{service}\b[^>]*>.*?<(?:\w+:)?XAddr>(.*?)</(?:\w+:)?XAddr>"
    match = re.search(pattern, xml, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _extract_profile_token(xml: str) -> str | None:
    match = re.search(r"<(?:\w+:)?Profiles\b[^>]*\btoken=[\"']([^\"']+)", xml, flags=re.IGNORECASE)
    return match.group(1) if match else None


@lru_cache(maxsize=64)
def session_for(rtsp_url: str) -> PTZSession:
    host, username, password = _credentials(rtsp_url)
    device_url = f"http://{host}:{PTZ_ONVIF_PORT}/onvif/device_service"
    caps_body = '<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>'
    caps = _post(device_url, "http://www.onvif.org/ver10/device/wsdl/GetCapabilities", caps_body, username, password)
    media_url = _extract_service(caps, "Media") or f"http://{host}:{PTZ_ONVIF_PORT}/onvif/media_service"
    ptz_url = _extract_service(caps, "PTZ") or f"http://{host}:{PTZ_ONVIF_PORT}/onvif/ptz_service"
    profiles = _post(media_url, "http://www.onvif.org/ver10/media/wsdl/GetProfiles", "<trt:GetProfiles/>", username, password)
    token = _extract_profile_token(profiles)
    if not token:
        raise PTZError("A câmera não retornou um profile token ONVIF")
    return PTZSession(host, username, password, token, ptz_url)


def probe(rtsp_url: str) -> dict:
    try:
        session = session_for(rtsp_url)
        return {"ok": True, "profile_token": session.profile_token, "ptz_url": session.ptz_url}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def move(rtsp_url: str, pan: float, tilt: float, speed: float = 0.55, duration: float = 0.35) -> None:
    session = session_for(rtsp_url)
    pan = max(-1.0, min(1.0, float(pan))) * max(0.05, min(1.0, speed))
    tilt = max(-1.0, min(1.0, float(tilt))) * max(0.05, min(1.0, speed))
    body = f"""
<tptz:ContinuousMove>
  <tptz:ProfileToken>{escape(session.profile_token)}</tptz:ProfileToken>
  <tptz:Velocity><tt:PanTilt x="{pan:.4f}" y="{tilt:.4f}"/></tptz:Velocity>
  <tptz:Timeout>PT{max(0.1, min(2.0, duration)):.2f}S</tptz:Timeout>
</tptz:ContinuousMove>"""
    _post(session.ptz_url, "http://www.onvif.org/ver20/ptz/wsdl/ContinuousMove", body, session.username, session.password)


def stop(rtsp_url: str) -> None:
    session = session_for(rtsp_url)
    body = f"""
<tptz:Stop>
  <tptz:ProfileToken>{escape(session.profile_token)}</tptz:ProfileToken>
  <tptz:PanTilt>true</tptz:PanTilt>
  <tptz:Zoom>false</tptz:Zoom>
</tptz:Stop>"""
    _post(session.ptz_url, "http://www.onvif.org/ver20/ptz/wsdl/Stop", body, session.username, session.password)


def pulse(rtsp_url: str, pan: float, tilt: float, speed: float = 0.55, duration: float = 0.28) -> None:
    move(rtsp_url, pan, tilt, speed, duration)
    timer = threading.Timer(max(0.12, duration), lambda: _safe_stop(rtsp_url))
    timer.daemon = True
    timer.start()


def _safe_stop(rtsp_url: str) -> None:
    try:
        stop(rtsp_url)
    except Exception:
        pass

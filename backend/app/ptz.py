from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import socket
import struct
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


DVRIP_PORT = 34567
DVRIP_OK = {100, 150, 515}
HOME_PRESET = 0


class PTZError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PTZSession:
    host: str
    username: str
    password: str
    profile_token: str
    ptz_url: str


@dataclass(slots=True)
class _MotionState:
    direction: str | None = None
    consecutive: int = 0
    last_at: float = 0.0
    blocked_until: float = 0.0


_motion_lock = threading.Lock()
_motion_state: dict[str, _MotionState] = {}


def _credentials(rtsp_url: str) -> tuple[str, str, str]:
    parsed = urlsplit(rtsp_url)
    if not parsed.hostname:
        raise PTZError("URL RTSP sem host")
    return parsed.hostname, parsed.username or "", parsed.password or ""


def sofia_hash(password: str) -> str:
    digest = hashlib.md5(password.encode("utf-8")).digest()
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return "".join(chars[(a + b) % 62] for a, b in zip(digest[::2], digest[1::2]))


def direction_from_vector(pan: float, tilt: float, deadzone: float = 0.18) -> str | None:
    """Map logical joystick axes to native iCSee/XMEye DVRIP directions.

    Physical testing showed horizontal movement is mirrored relative to the
    DVRIP labels, therefore only left/right are intentionally swapped.
    """
    pan = float(pan)
    tilt = float(tilt)
    horizontal = 0 if abs(pan) < deadzone else (1 if pan > 0 else -1)
    vertical = 0 if abs(tilt) < deadzone else (1 if tilt > 0 else -1)
    mapping = {
        (0, 0): None,
        (1, 0): "DirectionLeft",
        (-1, 0): "DirectionRight",
        (0, 1): "DirectionUp",
        (0, -1): "DirectionDown",
        (1, 1): "DirectionLeftUp",
        (1, -1): "DirectionLeftDown",
        (-1, 1): "DirectionRightUp",
        (-1, -1): "DirectionRightDown",
    }
    return mapping[(horizontal, vertical)]


def _motion_allowed(host: str, direction: str, max_consecutive: int) -> bool:
    now = time.monotonic()
    with _motion_lock:
        state = _motion_state.setdefault(host, _MotionState())
        if now < state.blocked_until:
            return False
        if now - state.last_at > 2.0 or state.direction != direction:
            state.direction = direction
            state.consecutive = 0
        state.consecutive += 1
        state.last_at = now
        if state.consecutive > max_consecutive:
            state.blocked_until = now + 1.25
            state.consecutive = 0
            return False
        return True


def _reset_motion_guard(host: str) -> None:
    with _motion_lock:
        _motion_state.pop(host, None)


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise PTZError("DVRIP: conexão encerrada pela câmera")
        data.extend(chunk)
    return bytes(data)


def _dvrip_request(sock: socket.socket, session: int, sequence: int, msg_id: int, payload: dict) -> tuple[dict, int]:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\x0a\x00"
    header = struct.pack("<BB2xII2xHI", 0xFF, 0, session, sequence, msg_id, len(raw))
    sock.sendall(header + raw)
    reply_header = _recv_exact(sock, 20)
    _, _, reply_session, _, _, body_len = struct.unpack("<BB2xII2xHI", reply_header)
    body = _recv_exact(sock, body_len) if body_len else b""
    text = body.rstrip(b"\x00").rstrip(b"\x0a").strip()
    if not text:
        return {}, reply_session
    try:
        return json.loads(text.decode("utf-8", "replace")), reply_session
    except json.JSONDecodeError as exc:
        raise PTZError("DVRIP: resposta não JSON; firmware pode exigir transporte criptografado") from exc


def _dvrip_login(host: str, username: str, password: str, timeout: float = 2.5) -> tuple[socket.socket, int, int]:
    sock = socket.create_connection((host, DVRIP_PORT), timeout=timeout)
    sock.settimeout(timeout)
    try:
        response, session = _dvrip_request(
            sock, 0, 0, 1000,
            {"EncryptType": "MD5", "LoginType": "DVRIP-Web", "PassWord": sofia_hash(password), "UserName": username},
        )
        ret = response.get("Ret")
        if ret not in DVRIP_OK:
            raise PTZError(f"DVRIP: login recusado (Ret {ret})")
        if response.get("SessionID"):
            try:
                session = int(str(response["SessionID"]), 16)
            except ValueError:
                pass
        return sock, session, 1
    except Exception:
        sock.close()
        raise


def _dvrip_ptz_payload(command: str, step: int, preset: int) -> dict:
    return {
        "Command": command,
        "Parameter": {
            "AUX": {"Number": 0, "Status": "On"},
            "Channel": 0,
            "MenuOpts": "Enter",
            "Pattern": "Start",
            "Preset": preset,
            "Step": step,
            "Tour": 0,
        },
    }


def _dvrip_send_ptz(sock: socket.socket, session: int, sequence: int, command: str, step: int, preset: int = 65535) -> int:
    response, _ = _dvrip_request(
        sock, session, sequence, 1400,
        {"Name": "OPPTZControl", "SessionID": f"0x{session:08X}", "OPPTZControl": _dvrip_ptz_payload(command, step, preset)},
    )
    ret = response.get("Ret")
    if ret not in DVRIP_OK:
        raise PTZError(f"DVRIP PTZ recusado (Ret {ret})")
    return sequence + 1


def _dvrip_probe(rtsp_url: str) -> dict:
    host, username, password = _credentials(rtsp_url)
    if not username:
        raise PTZError("DVRIP requer usuário da câmera")
    sock, _, _ = _dvrip_login(host, username, password)
    sock.close()
    return {"ok": True, "protocol": "dvrip", "port": DVRIP_PORT}


def _dvrip_pulse(
    rtsp_url: str,
    pan: float,
    tilt: float,
    speed: float,
    duration: float,
    *,
    max_step: int = 12,
    max_consecutive: int = 8,
) -> None:
    command = direction_from_vector(pan, tilt)
    if command is None:
        return
    host, username, password = _credentials(rtsp_url)
    if not username:
        raise PTZError("DVRIP requer usuário da câmera")
    if not _motion_allowed(host, command, max_consecutive):
        return
    sock, session, sequence = _dvrip_login(host, username, password)
    try:
        speed = max(0.05, min(1.0, float(speed)))
        step = max(1, min(max_step, int(round(speed * max_step))))
        sequence = _dvrip_send_ptz(sock, session, sequence, command, step, 65535)
        time.sleep(max(0.08, min(0.45, float(duration))))
        _dvrip_send_ptz(sock, session, sequence, "DirectionUp", 5, -1)
    finally:
        sock.close()


def _dvrip_stop(rtsp_url: str) -> None:
    host, username, password = _credentials(rtsp_url)
    if not username:
        raise PTZError("DVRIP requer usuário da câmera")
    sock, session, sequence = _dvrip_login(host, username, password)
    try:
        _dvrip_send_ptz(sock, session, sequence, "DirectionUp", 5, -1)
    finally:
        sock.close()
    _reset_motion_guard(host)


def _dvrip_preset(rtsp_url: str, command: str, preset: int = HOME_PRESET) -> None:
    host, username, password = _credentials(rtsp_url)
    if not username:
        raise PTZError("DVRIP requer usuário da câmera")
    sock, session, sequence = _dvrip_login(host, username, password)
    try:
        _dvrip_send_ptz(sock, session, sequence, command, 5, preset)
    finally:
        sock.close()
    _reset_motion_guard(host)


# --- ONVIF fallback for non-iCSee cameras ---------------------------------

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
          <wsse:Nonce>{nonce64}</wsse:Nonce><wsu:Created>{created}</wsu:Created>
        </wsse:UsernameToken>
      </wsse:Security>
    </s:Header>"""


def _envelope(body: str, username: str, password: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
{_security_header(username, password)}<s:Body>{body}</s:Body></s:Envelope>""".encode("utf-8")


def _post(url: str, action: str, body: str, username: str, password: str, timeout: float = 3.5) -> str:
    req = urllib.request.Request(url, data=_envelope(body, username, password), method="POST", headers={"Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise PTZError(f"ONVIF HTTP {exc.code}: {detail[:220]}") from exc
    except Exception as exc:
        raise PTZError(f"Falha ONVIF: {exc}") from exc


def _extract_service(xml: str, service: str) -> str | None:
    match = re.search(rf"<(?:\w+:)?{service}\b[^>]*>.*?<(?:\w+:)?XAddr>(.*?)</(?:\w+:)?XAddr>", xml, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _extract_profile_token(xml: str) -> str | None:
    match = re.search(r"<(?:\w+:)?Profiles\b[^>]*\btoken=[\"']([^\"']+)", xml, flags=re.IGNORECASE)
    return match.group(1) if match else None


@lru_cache(maxsize=64)
def session_for(rtsp_url: str) -> PTZSession:
    host, username, password = _credentials(rtsp_url)
    device_url = f"http://{host}:{PTZ_ONVIF_PORT}/onvif/device_service"
    caps = _post(device_url, "http://www.onvif.org/ver10/device/wsdl/GetCapabilities", '<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>', username, password)
    media_url = _extract_service(caps, "Media") or f"http://{host}:{PTZ_ONVIF_PORT}/onvif/media_service"
    ptz_url = _extract_service(caps, "PTZ") or f"http://{host}:{PTZ_ONVIF_PORT}/onvif/ptz_service"
    profiles = _post(media_url, "http://www.onvif.org/ver10/media/wsdl/GetProfiles", "<trt:GetProfiles/>", username, password)
    token = _extract_profile_token(profiles)
    if not token:
        raise PTZError("A câmera não retornou um profile token ONVIF")
    return PTZSession(host, username, password, token, ptz_url)


def _onvif_move(rtsp_url: str, pan: float, tilt: float, speed: float, duration: float) -> None:
    session = session_for(rtsp_url)
    speed = max(0.05, min(0.55, float(speed)))
    pan = max(-1.0, min(1.0, float(pan))) * speed
    tilt = max(-1.0, min(1.0, float(tilt))) * speed
    body = f"<tptz:ContinuousMove><tptz:ProfileToken>{escape(session.profile_token)}</tptz:ProfileToken><tptz:Velocity><tt:PanTilt x=\"{pan:.4f}\" y=\"{tilt:.4f}\"/></tptz:Velocity><tptz:Timeout>PT{max(0.1, min(0.45, duration)):.2f}S</tptz:Timeout></tptz:ContinuousMove>"
    _post(session.ptz_url, "http://www.onvif.org/ver20/ptz/wsdl/ContinuousMove", body, session.username, session.password)


def _onvif_stop(rtsp_url: str) -> None:
    session = session_for(rtsp_url)
    body = f"<tptz:Stop><tptz:ProfileToken>{escape(session.profile_token)}</tptz:ProfileToken><tptz:PanTilt>true</tptz:PanTilt><tptz:Zoom>false</tptz:Zoom></tptz:Stop>"
    _post(session.ptz_url, "http://www.onvif.org/ver20/ptz/wsdl/Stop", body, session.username, session.password)


def _onvif_preset(rtsp_url: str, command: str, preset: int = HOME_PRESET) -> None:
    session = session_for(rtsp_url)
    token = str(preset)
    if command == "SetPreset":
        body = f"<tptz:SetPreset><tptz:ProfileToken>{escape(session.profile_token)}</tptz:ProfileToken><tptz:PresetToken>{token}</tptz:PresetToken></tptz:SetPreset>"
        action = "http://www.onvif.org/ver20/ptz/wsdl/SetPreset"
    else:
        body = f"<tptz:GotoPreset><tptz:ProfileToken>{escape(session.profile_token)}</tptz:ProfileToken><tptz:PresetToken>{token}</tptz:PresetToken></tptz:GotoPreset>"
        action = "http://www.onvif.org/ver20/ptz/wsdl/GotoPreset"
    _post(session.ptz_url, action, body, session.username, session.password)


def probe(rtsp_url: str) -> dict:
    dvrip_error: str | None = None
    try:
        return _dvrip_probe(rtsp_url)
    except Exception as exc:
        dvrip_error = str(exc)
    try:
        session = session_for(rtsp_url)
        return {"ok": True, "protocol": "onvif", "ptz_url": session.ptz_url, "dvrip_error": dvrip_error}
    except Exception as exc:
        return {"ok": False, "error": f"DVRIP: {dvrip_error}; ONVIF: {exc}"}


def move(rtsp_url: str, pan: float, tilt: float, speed: float = 0.55, duration: float = 0.35) -> None:
    pulse(rtsp_url, pan, tilt, speed=speed, duration=duration)


def pulse(rtsp_url: str, pan: float, tilt: float, speed: float = 0.55, duration: float = 0.28, *, max_step: int = 12, max_consecutive: int = 8) -> None:
    try:
        _dvrip_pulse(rtsp_url, pan, tilt, speed, duration, max_step=max_step, max_consecutive=max_consecutive)
        return
    except Exception as dvrip_exc:
        try:
            _onvif_move(rtsp_url, pan, tilt, min(speed, 0.55), min(duration, 0.35))
            time.sleep(max(0.08, min(0.35, float(duration))))
            _onvif_stop(rtsp_url)
        except Exception as onvif_exc:
            raise PTZError(f"DVRIP falhou: {dvrip_exc}; ONVIF falhou: {onvif_exc}") from onvif_exc


def stop(rtsp_url: str) -> None:
    try:
        _dvrip_stop(rtsp_url)
        return
    except Exception:
        _onvif_stop(rtsp_url)


def set_home(rtsp_url: str) -> None:
    try:
        _dvrip_preset(rtsp_url, "SetPreset", HOME_PRESET)
        return
    except Exception as dvrip_exc:
        try:
            _onvif_preset(rtsp_url, "SetPreset", HOME_PRESET)
        except Exception as onvif_exc:
            raise PTZError(f"Não foi possível definir Home. DVRIP: {dvrip_exc}; ONVIF: {onvif_exc}") from onvif_exc


def goto_home(rtsp_url: str) -> None:
    try:
        _dvrip_preset(rtsp_url, "GotoPreset", HOME_PRESET)
        return
    except Exception as dvrip_exc:
        try:
            _onvif_preset(rtsp_url, "GotoPreset", HOME_PRESET)
        except Exception as onvif_exc:
            raise PTZError(f"Não foi possível retornar ao Home. DVRIP: {dvrip_exc}; ONVIF: {onvif_exc}") from onvif_exc

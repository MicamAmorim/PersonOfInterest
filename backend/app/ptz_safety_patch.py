from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from . import ptz


def _pin_service_host(raw_url: str | None, expected_host: str, fallback_path: str) -> str:
    """Keep ONVIF service discovery on the camera that was actually requested."""
    if not raw_url:
        return f"http://{expected_host}:{ptz.PTZ_ONVIF_PORT}{fallback_path}"
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port or ptz.PTZ_ONVIF_PORT
        host = expected_host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{port}"
        path = parsed.path or fallback_path
        return urlunsplit((parsed.scheme or "http", netloc, path, parsed.query, ""))
    except Exception:
        return f"http://{expected_host}:{ptz.PTZ_ONVIF_PORT}{fallback_path}"


def install() -> None:
    if getattr(ptz, "_poi_onvif_host_pinned", False):
        return

    @lru_cache(maxsize=64)
    def safe_session_for(rtsp_url: str) -> ptz.PTZSession:
        host, username, password = ptz._credentials(rtsp_url)
        device_url = f"http://{host}:{ptz.PTZ_ONVIF_PORT}/onvif/device_service"
        caps = ptz._post(
            device_url,
            "http://www.onvif.org/ver10/device/wsdl/GetCapabilities",
            '<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>',
            username,
            password,
        )
        media_url = _pin_service_host(ptz._extract_service(caps, "Media"), host, "/onvif/media_service")
        ptz_url = _pin_service_host(ptz._extract_service(caps, "PTZ"), host, "/onvif/ptz_service")
        profiles = ptz._post(
            media_url,
            "http://www.onvif.org/ver10/media/wsdl/GetProfiles",
            "<trt:GetProfiles/>",
            username,
            password,
        )
        token = ptz._extract_profile_token(profiles)
        if not token:
            raise ptz.PTZError("A câmera não retornou um profile token ONVIF")
        return ptz.PTZSession(host, username, password, token, ptz_url)

    ptz.session_for = safe_session_for
    ptz._poi_onvif_host_pinned = True

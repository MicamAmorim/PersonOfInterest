from __future__ import annotations

from typing import Any


def browser_stream_name(stream_name: str) -> str:
    return f"{stream_name}_browser"


def browser_stream_source(stream_name: str, local_restream_url) -> str:
    # Use the primary go2rtc stream through its explicit local RTSP endpoint.
    # This avoids any ambiguity in logical stream-name resolution inside the
    # FFmpeg module. Only video is transcoded; the camera's PCMA audio is copied
    # unchanged (WebRTC supports PCMA), avoiding an unnecessary Opus encoder.
    source = local_restream_url(stream_name)
    return f"ffmpeg:{source}#video=h264#audio=copy"


def install() -> None:
    from . import go2rtc

    if getattr(go2rtc, "_poi_browser_stream_patch", False):
        return

    original_upsert = go2rtc.upsert_stream
    original_delete = go2rtc.delete_stream

    def ensure_browser_stream(stream_name: str) -> Any:
        return original_upsert(
            browser_stream_name(stream_name),
            browser_stream_source(stream_name, go2rtc.local_restream_url),
        )

    def upsert_stream(
        stream_name: str,
        rtsp_url: str,
        extra_sources: Any = None,
    ) -> Any:
        result = original_upsert(stream_name, rtsp_url, extra_sources)
        if not result.ok or stream_name.endswith(("_talkback", "_browser")):
            return result

        # Keep the primary producer untouched for vision/recording. The browser
        # gets a separate lazy stream that transcodes only when viewed.
        browser_result = ensure_browser_stream(stream_name)
        if not browser_result.ok:
            result.warning = f"Stream H.264 do navegador indisponível: {browser_result.error}"
        return result

    def delete_stream(stream_name: str) -> Any:
        if not stream_name.endswith(("_talkback", "_browser")):
            try:
                original_delete(browser_stream_name(stream_name))
            except Exception:
                pass
        return original_delete(stream_name)

    go2rtc.browser_stream_name = browser_stream_name  # type: ignore[attr-defined]
    go2rtc.browser_stream_source = browser_stream_source  # type: ignore[attr-defined]
    go2rtc.ensure_browser_stream = ensure_browser_stream  # type: ignore[attr-defined]
    go2rtc.upsert_stream = upsert_stream
    go2rtc.delete_stream = delete_stream
    go2rtc._poi_browser_stream_patch = True  # type: ignore[attr-defined]

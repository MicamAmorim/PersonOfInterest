from __future__ import annotations

from typing import Any


def install() -> None:
    from . import go2rtc

    if getattr(go2rtc, "_poi_browser_stream_patch", False):
        return

    original_upsert = go2rtc.upsert_stream
    original_delete = go2rtc.delete_stream

    def browser_stream_name(stream_name: str) -> str:
        return f"{stream_name}_browser"

    def upsert_stream(
        stream_name: str,
        rtsp_url: str,
        extra_sources: Any = None,
    ) -> Any:
        result = original_upsert(stream_name, rtsp_url, extra_sources)
        if result.ok and not stream_name.endswith(("_talkback", "_browser")):
            browser_name = browser_stream_name(stream_name)
            source = f"ffmpeg:{stream_name}#video=h264#audio=copy#audio=opus"
            browser_result = original_upsert(browser_name, source)
            if not browser_result.ok:
                result.warning = f"Stream web H.264 indisponível: {browser_result.error}"
        return result

    def delete_stream(stream_name: str) -> Any:
        if not stream_name.endswith(("_talkback", "_browser")):
            try:
                original_delete(browser_stream_name(stream_name))
            except Exception:
                pass
        return original_delete(stream_name)

    go2rtc.browser_stream_name = browser_stream_name  # type: ignore[attr-defined]
    go2rtc.upsert_stream = upsert_stream
    go2rtc.delete_stream = delete_stream
    go2rtc._poi_browser_stream_patch = True  # type: ignore[attr-defined]

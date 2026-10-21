from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

try:
    import imageio_ffmpeg  # type: ignore
except Exception:  # pragma: no cover
    imageio_ffmpeg = None  # type: ignore


def _ffmpeg_executable() -> str | None:
    configured = os.getenv("FFMPEG_PATH", "").strip()
    if configured and Path(configured).is_file():
        return configured
    if imageio_ffmpeg is not None:
        try:
            value = imageio_ffmpeg.get_ffmpeg_exe()
            if value and Path(value).is_file():
                return str(value)
        except Exception:
            pass
    return None


def _command_line(args: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


def browser_stream_name(stream_name: str) -> str:
    return f"{stream_name}_browser"


def _browser_exec_source(rtsp_url: str) -> str | None:
    ffmpeg = _ffmpeg_executable()
    if not ffmpeg:
        return None
    args = [
        ffmpeg,
        "-hide_banner", "-loglevel", "warning",
        "-fflags", "nobuffer", "-flags", "low_delay",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264",
        "-g", "50",
        "-profile:v", "high",
        "-level:v", "4.1",
        "-preset:v", "superfast",
        "-tune:v", "zerolatency",
        "-pix_fmt:v", "yuv420p",
        "-c:a", "libopus",
        "-b:a", "64k",
        "-ar", "48000",
        "-ac", "1",
        "-user_agent", "ffmpeg/PersonOfInterest",
        "-rtsp_transport", "tcp",
        "-f", "rtsp",
        "{output}",
    ]
    return "exec:" + _command_line(args)


def install() -> None:
    from . import go2rtc

    if getattr(go2rtc, "_poi_browser_stream_patch", False):
        return

    original_upsert = go2rtc.upsert_stream
    original_delete = go2rtc.delete_stream

    def upsert_stream(
        stream_name: str,
        rtsp_url: str,
        extra_sources: Any = None,
    ) -> Any:
        result = original_upsert(stream_name, rtsp_url, extra_sources)
        if not result.ok or stream_name.endswith(("_talkback", "_browser")):
            return result

        # Browser playback must be deterministic. Keep the primary camera stream
        # untouched for vision/recording, and expose a separate lazy H.264/Opus
        # stream whose FFmpeg input is go2rtc's local RTSP restream. This avoids
        # opening a second direct connection to the physical camera while also
        # preventing stream.html from selecting the original HEVC producer.
        source = _browser_exec_source(go2rtc.local_restream_url(stream_name))
        if not source:
            result.warning = "FFmpeg local indisponível para stream H.264 do navegador"
            return result
        browser_result = original_upsert(browser_stream_name(stream_name), source)
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
    go2rtc.upsert_stream = upsert_stream
    go2rtc.delete_stream = delete_stream
    go2rtc._poi_browser_stream_patch = True  # type: ignore[attr-defined]

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

    def upsert_stream(
        stream_name: str,
        rtsp_url: str,
        extra_sources: Any = None,
    ) -> Any:
        result = original_upsert(stream_name, rtsp_url, extra_sources)
        if not result.ok or stream_name.endswith("_talkback"):
            return result

        # Keep the camera's original RTSP/HEVC producer first so vision,
        # recording and other RTSP consumers continue using the untouched
        # source. Add an H.264/Opus producer to the *same* go2rtc stream. go2rtc
        # starts this exec producer lazily only when a browser asks for codecs
        # the original camera cannot provide (typically HEVC -> H.264 WebRTC).
        browser_source = _browser_exec_source(rtsp_url)
        if not browser_source:
            result.warning = "FFmpeg local indisponível para fallback H.264 do navegador"
            return result
        try:
            go2rtc._request(  # type: ignore[attr-defined]
                "PUT",
                "/api/streams",
                {"name": stream_name, "src": [rtsp_url, browser_source]},
            )
        except Exception as exc:
            # The original stream is already valid; browser fallback failure must
            # never take vision/recording offline.
            result.warning = f"Fallback H.264 do navegador indisponível: {exc}"
        return result

    go2rtc.upsert_stream = upsert_stream
    go2rtc._poi_browser_stream_patch = True  # type: ignore[attr-defined]

from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path

from .config import DATA_DIR

try:
    import imageio_ffmpeg  # type: ignore
except Exception:  # pragma: no cover
    imageio_ffmpeg = None  # type: ignore


CACHE_DIR = DATA_DIR / "browser_media_cache"
_CODEC_RE = re.compile(r"Video:\s*([^,\s]+)", re.IGNORECASE)
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _ffmpeg_executable() -> str | None:
    configured = os.getenv("FFMPEG_PATH", "").strip()
    if configured and Path(configured).is_file():
        return configured
    if imageio_ffmpeg is not None:
        try:
            path = imageio_ffmpeg.get_ffmpeg_exe()
            if path and Path(path).is_file():
                return str(path)
        except Exception:
            pass
    return None


def video_codec(path: Path) -> str | None:
    ffmpeg = _ffmpeg_executable()
    if not ffmpeg or not path.is_file():
        return None
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        match = _CODEC_RE.search(completed.stderr or "")
        return match.group(1).strip().lower() if match else None
    except Exception:
        return None


def browser_compatible_path(recording_id: int, source: Path) -> Path:
    """Return a browser-safe MP4 while preserving the original recording.

    H.264 MP4 files are returned unchanged. HEVC/H.265 (and unknown video
    codecs) are transcoded lazily once and cached using source size/mtime as the
    cache key. Cache lookup happens before codec probing so subsequent byte-range
    requests stay cheap and behave like a normal static MP4.
    """
    try:
        source = source.resolve(strict=True)
        stat = source.stat()
    except OSError:
        return source

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fingerprint = f"{int(recording_id)}_{stat.st_size}_{stat.st_mtime_ns}"
    target = CACHE_DIR / f"recording_{fingerprint}_h264.mp4"
    if target.is_file() and target.stat().st_size > 0:
        return target

    codec = video_codec(source)
    if codec in {"h264", "avc1"}:
        return source

    ffmpeg = _ffmpeg_executable()
    if not ffmpeg:
        return source

    lock = _lock_for(fingerprint)
    with lock:
        if target.is_file() and target.stat().st_size > 0:
            return target
        temp = target.with_suffix(".tmp.mp4")
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        command = [
            ffmpeg,
            "-hide_banner", "-loglevel", "warning",
            "-i", str(source),
            "-map", "0:v:0?", "-map", "0:a:0?",
            "-c:v", "libx264",
            "-preset", "superfast",
            "-crf", "23",
            "-profile:v", "high",
            "-level:v", "4.1",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "64k",
            "-movflags", "+faststart",
            "-y", str(temp),
        ]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=900,
                check=False,
            )
            if completed.returncode == 0 and temp.is_file() and temp.stat().st_size > 0:
                os.replace(temp, target)
                return target
        except Exception:
            pass
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
    return source

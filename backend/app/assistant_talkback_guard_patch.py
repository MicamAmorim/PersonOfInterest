from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from . import assistant
from . import go2rtc
from .config import ASSISTANT_AUDIO_DIR
from .db import connection

try:  # PyAV is already used by the wake listener when available.
    import av  # type: ignore
except Exception:  # pragma: no cover - optional duration probe
    av = None  # type: ignore


_TALKBACK_PREPARE_SECONDS = 0.35
_TALKBACK_RELEASE_SECONDS = 0.35
_TALKBACK_PLAYBACK_MARGIN_SECONDS = 0.55


def _fallback_duration_seconds(text: str) -> float:
    """Conservative pt-BR TTS duration estimate when media metadata is unavailable."""
    words = max(1, len((text or "").split()))
    punctuation = sum((text or "").count(mark) for mark in ".,;:?!")
    return max(1.0, min(50.0, words * 0.40 + punctuation * 0.10 + 0.45))


def _audio_duration_seconds(path: Path, text: str) -> float:
    if av is not None:
        try:
            with av.open(str(path)) as container:
                if container.duration is not None:
                    seconds = float(container.duration) / float(av.time_base)
                    if 0.15 <= seconds <= 120.0:
                        return seconds
                for stream in container.streams.audio:
                    if stream.duration is not None and stream.time_base is not None:
                        seconds = float(stream.duration * stream.time_base)
                        if 0.15 <= seconds <= 120.0:
                            return seconds
        except Exception:
            pass
    return _fallback_duration_seconds(text)


def _fresh_talkback_stream(stream_name: str, rtsp_url: str) -> str:
    talkback = go2rtc.talkback_stream_name(stream_name)
    # iCSee/XMEye firmwares may leave OPTalk occupied after a previous consumer.
    # Recreate the dedicated stream for every utterance rather than reusing a
    # potentially stale DVRIP session.
    go2rtc.delete_stream(talkback)
    time.sleep(_TALKBACK_PREPARE_SECONDS)
    result = go2rtc.configure_talkback_stream(stream_name, rtsp_url)
    if not result.ok:
        raise RuntimeError(f"Talkback indisponível: {result.error or 'falha desconhecida'}")
    return talkback


def install() -> None:
    cls = assistant.AssistantManager
    if getattr(cls, "_poi_talkback_guard_installed", False):
        return

    def speak_guarded(
        self: Any,
        camera_id: int,
        text: str,
        *,
        voice_gender: str = "female",
    ) -> None:
        if not assistant.EDGE_TTS_AVAILABLE:
            raise RuntimeError(assistant.EDGE_TTS_ERROR or "edge-tts indisponível")
        voice = assistant.VOICE_BY_GENDER.get(
            voice_gender,
            assistant.VOICE_BY_GENDER["female"],
        )
        with connection() as conn:
            camera = conn.execute(
                "SELECT id, stream_name, rtsp_url, sync_status FROM cameras WHERE id = ? AND enabled = 1",
                (camera_id,),
            ).fetchone()
        if camera is None:
            raise LookupError("Câmera não encontrada ou desativada")
        if camera["sync_status"] != "ok":
            raise RuntimeError("Câmera não está online")

        stream_name = str(camera["stream_name"])
        rtsp_url = str(camera["rtsp_url"])
        talkback = go2rtc.talkback_stream_name(stream_name)

        # Keep the lock for the *whole audible utterance*. go2rtc's /api/ffmpeg
        # call can return before the camera finishes playback; releasing the lock
        # at that point lets a second TTS compete for the same OPTalk channel.
        with self.speak_lock:
            filename = f"tts_{camera_id}_{uuid.uuid4().hex}.mp3"
            path = ASSISTANT_AUDIO_DIR / filename
            ASSISTANT_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            asyncio.run(assistant.edge_tts.Communicate(text=text, voice=voice).save(str(path)))
            if not path.is_file() or path.stat().st_size < 256:
                raise RuntimeError("A síntese de voz não gerou áudio válido")

            duration = _audio_duration_seconds(path, text)
            file_url = f"http://127.0.0.1:8080/api/assistant/audio/{filename}"

            try:
                talkback = _fresh_talkback_stream(stream_name, rtsp_url)
                play = go2rtc.play_file_to_stream(talkback, file_url)
                if not play.ok:
                    # One clean retry covers a DVRIP session that was still being
                    # released by the camera at the first attempt.
                    go2rtc.delete_stream(talkback)
                    time.sleep(_TALKBACK_RELEASE_SECONDS)
                    talkback = _fresh_talkback_stream(stream_name, rtsp_url)
                    play = go2rtc.play_file_to_stream(talkback, file_url)
                if not play.ok:
                    raise RuntimeError(
                        f"Não foi possível reproduzir o TTS na câmera: {play.error or 'falha desconhecida'}"
                    )

                # Keep OPTalk exclusively owned until the MP3 should have ended.
                # This also makes web-search preface -> search -> final answer a
                # genuinely sequential interaction instead of overlapping audio.
                time.sleep(duration + _TALKBACK_PLAYBACK_MARGIN_SECONDS)
            finally:
                go2rtc.delete_stream(talkback)
                time.sleep(_TALKBACK_RELEASE_SECONDS)

    cls.speak = speak_guarded
    cls._poi_talkback_guard_installed = True

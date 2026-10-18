from __future__ import annotations

import io
import time
from typing import Any

from . import wake_word as ww
from .assistant import manager as assistant_manager
from .assistant_command_stt_patch import _merge_wake_and_command, _transcribe_command
from .assistant_conversation_patch import _extract_command_after_wake
from .assistant_tools import answer_command
from .config import WAKE_COMMAND_WHISPER_MODEL, WAKE_WHISPER_MODEL


LAB_SAMPLE_RATE = 16000
LAB_MAX_BYTES = 8 * 1024 * 1024
LAB_MAX_SECONDS = 15


def _decode_audio(payload: bytes) -> Any:
    if not payload:
        raise ValueError("Nenhum áudio recebido")
    if len(payload) > LAB_MAX_BYTES:
        raise ValueError("Áudio muito grande para o Tonho Lab")
    if not ww.WAKE_RUNTIME_AVAILABLE:
        raise RuntimeError(ww.WAKE_RUNTIME_ERROR or "Runtime de voz indisponível")

    container = ww.av.open(io.BytesIO(payload))
    try:
        audio_streams = [stream for stream in container.streams if stream.type == "audio"]
        if not audio_streams:
            raise ValueError("O arquivo enviado não contém áudio")
        stream = audio_streams[0]
        resampler = ww.av.AudioResampler(format="s16", layout="mono", rate=LAB_SAMPLE_RATE)
        chunks: list[Any] = []
        for packet in container.demux(stream):
            for frame in packet.decode():
                outputs = resampler.resample(frame)
                if outputs is None:
                    continue
                if not isinstance(outputs, list):
                    outputs = [outputs]
                for output in outputs:
                    data = output.to_ndarray().reshape(-1)
                    if data.size:
                        chunks.append(data.astype(ww.np.float32) / 32768.0)
        if not chunks:
            raise ValueError("Não consegui extrair amostras de áudio")
        audio = ww.np.concatenate(chunks).astype(ww.np.float32, copy=False)
        maximum = LAB_SAMPLE_RATE * LAB_MAX_SECONDS
        if audio.size > maximum:
            audio = audio[:maximum]
        return audio
    finally:
        container.close()


def _camera_context(camera_id: int) -> dict[str, Any]:
    settings = assistant_manager.settings_for(camera_id)
    return {
        "camera_id": int(camera_id),
        "camera_name": str(settings.get("camera_name") or f"Câmera {camera_id}"),
        "timezone": str(settings.get("timezone") or "UTC"),
        "voice_gender": str(settings.get("voice_gender") or "female"),
    }


def _answer_from_transcripts(
    camera_id: int,
    *,
    fast_transcript: str,
    command_transcript: str,
    require_wake: bool,
    speak: bool,
) -> dict[str, Any]:
    context = _camera_context(camera_id)
    fast = (fast_transcript or "").strip()
    strong = (command_transcript or "").strip()
    fast_wake = ww.matches_wake_phrase(fast)
    strong_wake = ww.matches_wake_phrase(strong)
    wake_detected = fast_wake or strong_wake

    if require_wake and not wake_detected:
        return {
            **context,
            "ok": True,
            "wake_detected": False,
            "wake_detected_by": None,
            "fast_transcript": fast,
            "command_transcript": strong,
            "command": "",
            "intent": "no_wake",
            "answer": "Não detectei ‘Oi, Tonho’. Tente novamente ou desligue a exigência de wake word no Lab.",
            "certainty": "system",
            "person_id": None,
            "spoken": False,
            "wake_model": WAKE_WHISPER_MODEL,
            "command_model": WAKE_COMMAND_WHISPER_MODEL,
        }

    if strong_wake:
        routed = strong
    elif fast_wake:
        routed = _merge_wake_and_command(fast, strong)
    else:
        routed = strong or fast

    command = _extract_command_after_wake(routed) if wake_detected else routed
    command = (command or "").strip()
    if wake_detected and not command:
        return {
            **context,
            "ok": True,
            "wake_detected": True,
            "wake_detected_by": "base" if strong_wake else "tiny",
            "fast_transcript": fast,
            "command_transcript": strong,
            "command": "",
            "intent": "wake",
            "answer": "Wake word detectado. Diga um comando.",
            "certainty": "system",
            "person_id": None,
            "spoken": False,
            "wake_model": WAKE_WHISPER_MODEL,
            "command_model": WAKE_COMMAND_WHISPER_MODEL,
        }

    answer = answer_command(camera_id, command, context["timezone"])
    spoken = False
    speak_error: str | None = None
    if speak:
        try:
            assistant_manager.speak(
                camera_id,
                answer.text,
                voice_gender=context["voice_gender"],
            )
            spoken = True
        except Exception as exc:
            speak_error = str(exc)

    return {
        **context,
        "ok": True,
        "wake_detected": wake_detected,
        "wake_detected_by": (
            "base" if strong_wake else "tiny" if fast_wake else None
        ),
        "fast_transcript": fast,
        "command_transcript": strong,
        "command": command,
        "intent": answer.intent,
        "answer": answer.text,
        "certainty": answer.certainty,
        "person_id": answer.person_id,
        "spoken": spoken,
        "speak_error": speak_error,
        "wake_model": WAKE_WHISPER_MODEL,
        "command_model": WAKE_COMMAND_WHISPER_MODEL,
    }


def analyze_audio(
    camera_id: int,
    payload: bytes,
    *,
    require_wake: bool = True,
    speak: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    audio = _decode_audio(payload)
    rms = float(ww.np.sqrt(ww.np.mean(ww.np.square(audio)))) if audio.size else 0.0

    # Lab intentionally runs both models. That gives a clean A/B diagnostic:
    # whether failure came from always-on wake STT, command STT, or the parser.
    fast_started = time.perf_counter()
    fast = wake_manager_transcribe(audio)
    fast_ms = round((time.perf_counter() - fast_started) * 1000.0, 1)

    strong_started = time.perf_counter()
    strong = _transcribe_command(ww.manager, audio)
    strong_ms = round((time.perf_counter() - strong_started) * 1000.0, 1)

    result = _answer_from_transcripts(
        camera_id,
        fast_transcript=fast,
        command_transcript=strong,
        require_wake=require_wake,
        speak=speak,
    )
    result.update(
        {
            "rms": round(rms, 5),
            "fast_latency_ms": fast_ms,
            "command_latency_ms": strong_ms,
            "total_latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
        }
    )
    return result


def wake_manager_transcribe(audio: Any) -> str:
    # Use the original tiny manager method. assistant_command_stt_patch only
    # overrides it through thread-local state while camera processing is active.
    return str(ww.manager._transcribe(audio) or "").strip()


def analyze_text(
    camera_id: int,
    text: str,
    *,
    require_wake: bool = False,
    speak: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("Digite uma frase para testar")
    result = _answer_from_transcripts(
        camera_id,
        fast_transcript=raw,
        command_transcript=raw,
        require_wake=require_wake,
        speak=speak,
    )
    result.update(
        {
            "rms": None,
            "fast_latency_ms": 0.0,
            "command_latency_ms": 0.0,
            "total_latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
        }
    )
    return result

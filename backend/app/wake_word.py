from __future__ import annotations

import difflib
import threading
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any

from . import go2rtc
from .assistant import manager as assistant_manager
from .config import (
    BODY_REID_THRESHOLD,
    WAKE_AFTER_SPEECH_MUTE_SECONDS,
    WAKE_CHUNK_SECONDS,
    WAKE_CONTEXT_SECONDS,
    WAKE_MIN_RMS,
    WAKE_OVERLAP_SECONDS,
    WAKE_PHRASE,
    WAKE_RESPONSE_COOLDOWN_SECONDS,
    WAKE_WHISPER_MODEL,
)
from .db import connection, utc_now

try:
    import av  # type: ignore
    import numpy as np  # type: ignore
    from faster_whisper import WhisperModel  # type: ignore

    WAKE_RUNTIME_AVAILABLE = True
    WAKE_RUNTIME_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - optional runtime boundary
    av = None  # type: ignore
    np = None  # type: ignore
    WhisperModel = None  # type: ignore
    WAKE_RUNTIME_AVAILABLE = False
    WAKE_RUNTIME_ERROR = str(exc)


SAMPLE_RATE = 16000


def normalize_phrase(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in normalized).split())


def matches_wake_phrase(text: str) -> bool:
    """Recognize 'Oi, Tonho!' while tolerating common Whisper spellings."""
    normalized = normalize_phrase(text)
    words = normalized.split()
    if not words:
        return False
    target = normalize_phrase(WAKE_PHRASE)
    if target and target in normalized:
        return True

    accepted = {"tonho", "tonio", "toni", "tony", "antonio"}
    for index, word in enumerate(words):
        if word != "oi":
            continue
        for candidate in words[index + 1:index + 3]:
            if candidate in accepted:
                return True
            if difflib.SequenceMatcher(None, candidate, "tonho").ratio() >= 0.76:
                return True
    return False


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except Exception:
        return None


class WakeWordManager:
    """Per-camera local speech listener for the first conversational prototype.

    Audio comes from go2rtc's localhost RTSP restream. faster-whisper performs
    speech-to-text locally. Only the existing Edge TTS response leaves the PC.
    """

    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()
        self.model_lock = threading.Lock()
        self._model: Any | None = None
        self._workers: dict[int, tuple[threading.Thread, threading.Event]] = {}
        self._camera_state: dict[int, dict[str, Any]] = {}
        self._last_trigger_monotonic: dict[int, float] = {}
        self.status = "stopped"
        self.error: str | None = None
        self.last_wake: dict[str, Any] | None = None

    @property
    def available(self) -> bool:
        return WAKE_RUNTIME_AVAILABLE

    def ensure_schema(self) -> None:
        with connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS camera_wake_settings (
                    camera_id INTEGER PRIMARY KEY,
                    wake_enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS assistant_wake_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id INTEGER NOT NULL,
                    transcript TEXT NOT NULL,
                    matched INTEGER NOT NULL DEFAULT 0,
                    response_text TEXT,
                    certainty TEXT,
                    person_id INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
                    FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_assistant_wake_camera_created
                    ON assistant_wake_log(camera_id, created_at DESC);
                """
            )
            conn.commit()

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.ensure_schema()
            self.stop_event.clear()
            self.wake_event.clear()
            self.thread = threading.Thread(target=self._run, name="poi-wake-coordinator", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        with self.lock:
            workers = list(self._workers.values())
        for _, event in workers:
            event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3.0)
        for thread, _ in workers:
            if thread.is_alive():
                thread.join(timeout=1.5)
        with self.lock:
            self._workers.clear()
        self.status = "stopped"

    def notify_change(self) -> None:
        self.wake_event.set()

    def settings_for(self, camera_id: int) -> dict[str, Any]:
        self.ensure_schema()
        with connection() as conn:
            camera = conn.execute("SELECT id FROM cameras WHERE id = ?", (camera_id,)).fetchone()
            if camera is None:
                raise LookupError("Câmera não encontrada")
            row = conn.execute(
                "SELECT wake_enabled, updated_at FROM camera_wake_settings WHERE camera_id = ?",
                (camera_id,),
            ).fetchone()
        return {
            "wake_enabled": bool(row["wake_enabled"]) if row else False,
            "wake_updated_at": row["updated_at"] if row else None,
        }

    def update_setting(self, camera_id: int, enabled: bool) -> dict[str, Any]:
        self.ensure_schema()
        with connection() as conn:
            if conn.execute("SELECT id FROM cameras WHERE id = ?", (camera_id,)).fetchone() is None:
                raise LookupError("Câmera não encontrada")
            now = utc_now()
            conn.execute(
                """INSERT INTO camera_wake_settings(camera_id, wake_enabled, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET
                    wake_enabled = excluded.wake_enabled,
                    updated_at = excluded.updated_at""",
                (camera_id, int(enabled), now),
            )
            conn.commit()
        self.notify_change()
        return self.settings_for(camera_id)

    def enrich_settings(self, settings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.ensure_schema()
        with connection() as conn:
            rows = conn.execute("SELECT camera_id, wake_enabled, updated_at FROM camera_wake_settings").fetchall()
        by_camera = {int(row["camera_id"]): row for row in rows}
        output: list[dict[str, Any]] = []
        for item in settings:
            data = dict(item)
            row = by_camera.get(int(data["camera_id"]))
            data["wake_enabled"] = bool(row["wake_enabled"]) if row else False
            data["wake_updated_at"] = row["updated_at"] if row else None
            output.append(data)
        return output

    def state(self) -> dict[str, Any]:
        self.ensure_schema()
        with connection() as conn:
            enabled = int(conn.execute("SELECT COUNT(*) FROM camera_wake_settings WHERE wake_enabled = 1").fetchone()[0])
        with self.lock:
            cameras = {str(key): dict(value) for key, value in self._camera_state.items()}
            active_workers = sum(1 for thread, _ in self._workers.values() if thread.is_alive())
        return {
            "status": self.status,
            "error": self.error,
            "available": self.available,
            "runtime_error": WAKE_RUNTIME_ERROR,
            "phrase": WAKE_PHRASE,
            "model": WAKE_WHISPER_MODEL,
            "enabled_cameras": enabled,
            "active_workers": active_workers,
            "last_wake": self.last_wake,
            "cameras": cameras,
        }

    def _enabled_cameras(self) -> dict[int, dict[str, Any]]:
        with connection() as conn:
            rows = conn.execute(
                """SELECT c.id, c.name, c.stream_name, c.sync_status, s.voice_gender
                FROM cameras c
                JOIN camera_assistant_settings s ON s.camera_id = c.id AND s.enabled = 1
                JOIN camera_wake_settings w ON w.camera_id = c.id AND w.wake_enabled = 1
                WHERE c.enabled = 1 AND c.sync_status = 'ok'"""
            ).fetchall()
        return {int(row["id"]): dict(row) for row in rows}

    def _run(self) -> None:  # pragma: no cover - integration thread
        if not WAKE_RUNTIME_AVAILABLE:
            self.status = "unavailable"
            self.error = WAKE_RUNTIME_ERROR or "faster-whisper indisponível"
            return
        self.status = "running"
        self.error = None
        while not self.stop_event.is_set():
            try:
                desired = self._enabled_cameras()
                self._sync_workers(desired)
                self.status = "running"
                self.error = None
            except Exception as exc:
                self.status = "error"
                self.error = str(exc)
            self.wake_event.wait(2.0)
            self.wake_event.clear()
        self._sync_workers({})

    def _sync_workers(self, desired: dict[int, dict[str, Any]]) -> None:
        with self.lock:
            current_ids = set(self._workers)
            desired_ids = set(desired)
            for camera_id in current_ids - desired_ids:
                _, stop = self._workers.pop(camera_id)
                stop.set()
                self._camera_state[camera_id] = {"status": "disabled", "updated_at": utc_now()}
            for camera_id in desired_ids - current_ids:
                stop = threading.Event()
                thread = threading.Thread(
                    target=self._camera_worker,
                    args=(desired[camera_id], stop),
                    name=f"poi-wake-camera-{camera_id}",
                    daemon=True,
                )
                self._workers[camera_id] = (thread, stop)
                self._camera_state[camera_id] = {
                    "status": "starting",
                    "camera_name": desired[camera_id]["name"],
                    "updated_at": utc_now(),
                }
                thread.start()

    def _set_camera_state(self, camera_id: int, **values: Any) -> None:
        with self.lock:
            state = dict(self._camera_state.get(camera_id) or {})
            state.update(values)
            state["updated_at"] = utc_now()
            self._camera_state[camera_id] = state

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        if not WAKE_RUNTIME_AVAILABLE:
            raise RuntimeError(WAKE_RUNTIME_ERROR or "faster-whisper indisponível")
        with self.model_lock:
            if self._model is None:
                self.status = "loading_model"
                self._model = WhisperModel(WAKE_WHISPER_MODEL, device="cpu", compute_type="int8")
                self.status = "running"
        return self._model

    def _camera_worker(self, camera: dict[str, Any], stop: threading.Event) -> None:
        camera_id = int(camera["id"])
        stream_url = go2rtc.local_restream_url(str(camera["stream_name"]))
        while not self.stop_event.is_set() and not stop.is_set():
            try:
                self._listen_stream(camera, stream_url, stop)
            except Exception as exc:
                self._set_camera_state(camera_id, status="error", error=str(exc))
                stop.wait(3.0)
        if not self.stop_event.is_set():
            self._set_camera_state(camera_id, status="disabled")

    def _listen_stream(self, camera: dict[str, Any], stream_url: str, stop: threading.Event) -> None:
        camera_id = int(camera["id"])
        self._set_camera_state(camera_id, status="connecting", error=None)
        container = av.open(stream_url, options={"rtsp_transport": "tcp"})
        try:
            audio_streams = [stream for stream in container.streams if stream.type == "audio"]
            if not audio_streams:
                self._set_camera_state(camera_id, status="no_audio", error="O stream não expõe faixa de áudio")
                stop.wait(4.0)
                return
            audio_stream = audio_streams[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            target = max(SAMPLE_RATE, int(SAMPLE_RATE * WAKE_CHUNK_SECONDS))
            overlap = max(0, min(target // 2, int(SAMPLE_RATE * WAKE_OVERLAP_SECONDS)))
            chunks: list[Any] = []
            samples_count = 0
            self._set_camera_state(camera_id, status="listening", error=None)

            for packet in container.demux(audio_stream):
                if self.stop_event.is_set() or stop.is_set():
                    return
                for frame in packet.decode():
                    if self.stop_event.is_set() or stop.is_set():
                        return
                    if assistant_manager.speak_lock.locked():
                        chunks.clear()
                        samples_count = 0
                        continue
                    output_frames = resampler.resample(frame)
                    if output_frames is None:
                        continue
                    if not isinstance(output_frames, list):
                        output_frames = [output_frames]
                    for output in output_frames:
                        data = output.to_ndarray().reshape(-1)
                        if data.size == 0:
                            continue
                        data = data.astype(np.float32) / 32768.0
                        chunks.append(data)
                        samples_count += int(data.size)
                    if samples_count < target:
                        continue

                    audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
                    window = np.asarray(audio[:target], dtype=np.float32)
                    keep = np.asarray(audio[max(0, target - overlap):], dtype=np.float32) if overlap else np.asarray(audio[target:], dtype=np.float32)
                    chunks = [keep] if keep.size else []
                    samples_count = int(keep.size)
                    self._process_audio_window(camera, window)
        finally:
            container.close()

    def _process_audio_window(self, camera: dict[str, Any], audio: Any) -> None:
        camera_id = int(camera["id"])
        if audio.size == 0:
            return
        rms = float(np.sqrt(np.mean(np.square(audio))))
        if rms < WAKE_MIN_RMS:
            return
        transcript = self._transcribe(audio)
        if not transcript:
            return
        matched = matches_wake_phrase(transcript)
        self._set_camera_state(
            camera_id,
            status="listening",
            last_transcript=transcript,
            last_rms=round(rms, 5),
        )
        if not matched:
            self._log(camera_id, transcript, False, None, None, None)
            return

        now_mono = time.monotonic()
        last = self._last_trigger_monotonic.get(camera_id, 0.0)
        if now_mono - last < WAKE_RESPONSE_COOLDOWN_SECONDS:
            return
        self._last_trigger_monotonic[camera_id] = now_mono

        response, certainty, person_id = self._response_for(camera_id)
        voice_gender = str(camera.get("voice_gender") or "female")
        self._set_camera_state(camera_id, status="responding", last_transcript=transcript)
        try:
            assistant_manager.speak(camera_id, response, voice_gender=voice_gender)
            # go2rtc can return before the speaker has fully finished the file;
            # give the camera a short half-duplex guard before listening again.
            self._last_trigger_monotonic[camera_id] = time.monotonic() + max(0.0, WAKE_AFTER_SPEECH_MUTE_SECONDS)
            self.last_wake = {
                "camera_id": camera_id,
                "camera_name": camera.get("name"),
                "transcript": transcript,
                "response": response,
                "certainty": certainty,
                "person_id": person_id,
                "created_at": utc_now(),
            }
            self._log(camera_id, transcript, True, response, certainty, person_id)
            self._set_camera_state(camera_id, status="listening", last_response=response, error=None)
        except Exception as exc:
            self._log(camera_id, transcript, True, None, certainty, person_id)
            self._set_camera_state(camera_id, status="error", error=str(exc))

    def _transcribe(self, audio: Any) -> str:
        model = self._ensure_model()
        with self.model_lock:
            segments, _ = model.transcribe(
                audio,
                language="pt",
                beam_size=1,
                best_of=1,
                temperature=0.0,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt="Frase de ativação: Oi, Tonho!",
            )
            return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()

    def _response_for(self, camera_id: int) -> tuple[str, str, int | None]:
        with connection() as conn:
            rows = conn.execute(
                """SELECT e.created_at, e.person_id, e.probable_person_id, e.body_confidence,
                    p.name person_name, pp.name probable_person_name
                FROM events e
                LEFT JOIN persons p ON p.id = e.person_id
                LEFT JOIN persons pp ON pp.id = e.probable_person_id
                WHERE e.camera_id = ? AND COALESCE(e.identity_state, '') <> 'false_positive'
                ORDER BY e.created_at DESC LIMIT 24""",
                (camera_id,),
            ).fetchall()

        now = datetime.now(timezone.utc)
        probable: tuple[str, int] | None = None
        for row in rows:
            created = _parse_iso(str(row["created_at"] or ""))
            if created is None or (now - created).total_seconds() > WAKE_CONTEXT_SECONDS:
                continue
            if row["person_id"] is not None and row["person_name"]:
                return f"Oi, {row['person_name']}!", "known", int(row["person_id"])
            if (
                probable is None
                and row["probable_person_id"] is not None
                and row["probable_person_name"]
                and float(row["body_confidence"] or 0.0) >= BODY_REID_THRESHOLD
            ):
                probable = (str(row["probable_person_name"]), int(row["probable_person_id"]))
        if probable is not None:
            return f"Oi, {probable[0]}?", "probable", probable[1]
        return "Oi!", "unknown", None

    def _log(
        self,
        camera_id: int,
        transcript: str,
        matched: bool,
        response_text: str | None,
        certainty: str | None,
        person_id: int | None,
    ) -> None:
        try:
            with connection() as conn:
                conn.execute(
                    """INSERT INTO assistant_wake_log(
                        camera_id, transcript, matched, response_text, certainty, person_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (camera_id, transcript[:500], int(matched), response_text, certainty, person_id, utc_now()),
                )
                conn.commit()
        except Exception:
            pass


manager = WakeWordManager()

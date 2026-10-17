from __future__ import annotations

import asyncio
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import go2rtc
from .config import (
    ASSISTANT_AUDIO_DIR,
    ASSISTANT_POLL_SECONDS,
    ASSISTANT_SETTLE_SECONDS,
    ASSISTANT_UNKNOWN_FACE_QUALITY,
    BODY_REID_THRESHOLD,
)
from .db import connection, utc_now

try:
    import edge_tts  # type: ignore
    EDGE_TTS_AVAILABLE = True
    EDGE_TTS_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - optional runtime boundary
    edge_tts = None  # type: ignore
    EDGE_TTS_AVAILABLE = False
    EDGE_TTS_ERROR = str(exc)


VOICE_BY_GENDER = {
    "female": "pt-BR-FranciscaNeural",
    "male": "pt-BR-AntonioNeural",
}
DEFAULT_TIMEZONE = "UTC"
DEFAULT_INTERVAL_MINUTES = 30


def daypart_for(local_dt: datetime) -> tuple[str, str]:
    hour = local_dt.hour
    if 5 <= hour < 12:
        return "morning", "Bom dia"
    if 12 <= hour < 18:
        return "afternoon", "Boa tarde"
    return "night", "Boa noite"


def greeting_message(name: str, greeting: str, probable: bool = False) -> str:
    suffix = "?" if probable else "."
    return f"{greeting}, {name}{suffix}"


def casual_message(name: str, probable: bool = False) -> str:
    if probable:
        return f"Oi, {name}? Estou de olho!"
    return f"Oi, {name}, estou de olho!"


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


class AssistantManager:
    """Camera speaker assistant driven by identity events.

    Identity hierarchy is intentionally strict:
    - person_id (face/manual confirmation) is treated as known;
    - probable_person_id is only a body-ReID suggestion and is spoken as a question;
    - a high-quality unknown face never gets overwritten by a body guess.
    """

    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()
        self.speak_lock = threading.Lock()
        self.status = "stopped"
        self.error: str | None = None
        self.last_speech: dict[str, Any] | None = None
        self.started_at = utc_now()

    @property
    def available(self) -> bool:
        return EDGE_TTS_AVAILABLE

    def ensure_schema(self) -> None:
        ASSISTANT_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        with connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS camera_assistant_settings (
                    camera_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    interval_minutes INTEGER NOT NULL DEFAULT 30,
                    voice_gender TEXT NOT NULL DEFAULT 'female',
                    timezone TEXT NOT NULL DEFAULT 'UTC',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS assistant_event_state (
                    event_id INTEGER PRIMARY KEY,
                    outcome TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS assistant_speech_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id INTEGER NOT NULL,
                    event_id INTEGER,
                    subject_key TEXT NOT NULL,
                    certainty TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    local_date TEXT,
                    daypart TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    spoken_at TEXT NOT NULL,
                    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_assistant_log_subject_spoken
                    ON assistant_speech_log(subject_key, spoken_at DESC);
                CREATE INDEX IF NOT EXISTS idx_assistant_log_turn
                    ON assistant_speech_log(subject_key, local_date, daypart, kind, status);
                """
            )
            conn.commit()

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.ensure_schema()
            self.started_at = utc_now()
            self.stop_event.clear()
            self.wake_event.clear()
            self.thread = threading.Thread(target=self._run, name="poi-assistant", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3.0)

    def notify_change(self) -> None:
        self.wake_event.set()

    def state(self) -> dict[str, Any]:
        self.ensure_schema()
        with connection() as conn:
            enabled = int(conn.execute("SELECT COUNT(*) FROM camera_assistant_settings WHERE enabled = 1").fetchone()[0])
            spoken = int(conn.execute("SELECT COUNT(*) FROM assistant_speech_log WHERE status = 'spoken'").fetchone()[0])
        return {
            "status": self.status,
            "error": self.error,
            "available": self.available,
            "edge_tts_error": EDGE_TTS_ERROR,
            "enabled_cameras": enabled,
            "spoken_count": spoken,
            "last_speech": self.last_speech,
            "unknown_face_quality_threshold": ASSISTANT_UNKNOWN_FACE_QUALITY,
            "body_probable_threshold": BODY_REID_THRESHOLD,
            "voices": VOICE_BY_GENDER,
        }

    def settings_for(self, camera_id: int) -> dict[str, Any]:
        self.ensure_schema()
        with connection() as conn:
            camera = conn.execute("SELECT id, name FROM cameras WHERE id = ?", (camera_id,)).fetchone()
            if camera is None:
                raise LookupError("Câmera não encontrada")
            row = conn.execute("SELECT * FROM camera_assistant_settings WHERE camera_id = ?", (camera_id,)).fetchone()
        if row:
            data = dict(row)
        else:
            data = {
                "camera_id": camera_id,
                "enabled": 0,
                "interval_minutes": DEFAULT_INTERVAL_MINUTES,
                "voice_gender": "female",
                "timezone": DEFAULT_TIMEZONE,
                "updated_at": None,
            }
        data["enabled"] = bool(data.get("enabled"))
        data["camera_name"] = str(camera["name"])
        return data

    def list_settings(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with connection() as conn:
            rows = conn.execute("SELECT id FROM cameras ORDER BY name COLLATE NOCASE").fetchall()
        return [self.settings_for(int(row["id"])) for row in rows]

    def update_settings(
        self,
        camera_id: int,
        *,
        enabled: bool,
        interval_minutes: int,
        voice_gender: str,
        timezone_name: str,
    ) -> dict[str, Any]:
        self.ensure_schema()
        interval_minutes = max(1, min(1440, int(interval_minutes)))
        if voice_gender not in VOICE_BY_GENDER:
            raise ValueError("Voz deve ser feminina ou masculina")
        try:
            ZoneInfo(timezone_name)
        except Exception as exc:
            raise ValueError(f"Fuso horário inválido: {timezone_name}") from exc
        with connection() as conn:
            if conn.execute("SELECT id FROM cameras WHERE id = ?", (camera_id,)).fetchone() is None:
                raise LookupError("Câmera não encontrada")
            now = utc_now()
            conn.execute(
                """INSERT INTO camera_assistant_settings(camera_id, enabled, interval_minutes, voice_gender, timezone, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    interval_minutes = excluded.interval_minutes,
                    voice_gender = excluded.voice_gender,
                    timezone = excluded.timezone,
                    updated_at = excluded.updated_at""",
                (camera_id, int(enabled), interval_minutes, voice_gender, timezone_name, now),
            )
            conn.commit()
        self.notify_change()
        return self.settings_for(camera_id)

    def _run(self) -> None:  # pragma: no cover - background integration
        if not EDGE_TTS_AVAILABLE:
            self.status = "unavailable"
            self.error = EDGE_TTS_ERROR or "edge-tts indisponível"
            return
        self.status = "running"
        self.error = None
        while not self.stop_event.is_set():
            try:
                self._poll_once()
                self._cleanup_audio()
                self.status = "running"
                self.error = None
            except Exception as exc:
                self.status = "error"
                self.error = str(exc)
            self.wake_event.wait(max(0.4, ASSISTANT_POLL_SECONDS))
            self.wake_event.clear()

    def _poll_once(self) -> None:
        with connection() as conn:
            rows = conn.execute(
                """SELECT e.*, c.name AS camera_name, c.stream_name, c.rtsp_url, c.sync_status,
                    s.interval_minutes, s.voice_gender, s.timezone, s.updated_at AS assistant_updated_at,
                    p.name AS person_name, pp.name AS probable_person_name,
                    fs.quality AS face_quality
                FROM events e
                JOIN cameras c ON c.id = e.camera_id
                JOIN camera_assistant_settings s ON s.camera_id = e.camera_id AND s.enabled = 1
                LEFT JOIN persons p ON p.id = e.person_id
                LEFT JOIN persons pp ON pp.id = e.probable_person_id
                LEFT JOIN face_samples fs ON fs.event_id = e.id
                LEFT JOIN assistant_event_state aes ON aes.event_id = e.id
                WHERE aes.event_id IS NULL
                  AND e.created_at >= ?
                  AND e.created_at >= s.updated_at
                ORDER BY e.created_at ASC
                LIMIT 24""",
                (self.started_at,),
            ).fetchall()
        for row in rows:
            if self.stop_event.is_set():
                return
            self._handle_event(dict(row))

    def _mark_event(self, event_id: int, outcome: str) -> None:
        with connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO assistant_event_state(event_id, outcome, evaluated_at) VALUES (?, ?, ?)",
                (event_id, outcome, utc_now()),
            )
            conn.commit()

    def _event_age_seconds(self, event: dict[str, Any]) -> float:
        created = _parse_iso(str(event.get("created_at") or ""))
        if created is None:
            return 9999.0
        return max(0.0, (datetime.now(timezone.utc) - created).total_seconds())

    def _handle_event(self, event: dict[str, Any]) -> None:
        event_id = int(event["id"])
        camera_id = int(event["camera_id"])
        state = str(event.get("identity_state") or "")
        if state == "false_positive":
            self._mark_event(event_id, "false_positive")
            return
        # Identity owns certainty. Never discard an event merely because face/body
        # indexing is temporarily slow; leave it unconsumed and revisit next poll.
        if state == "pending":
            return

        certainty: str | None = None
        subject_key: str | None = None
        name: str | None = None

        if event.get("person_id") is not None and event.get("person_name"):
            certainty = "known"
            subject_key = f"person:{int(event['person_id'])}"
            name = str(event["person_name"])
        else:
            face_quality = float(event.get("face_quality") or 0.0)
            if state == "unknown" and face_quality >= ASSISTANT_UNKNOWN_FACE_QUALITY:
                certainty = "unknown"
                cluster = event.get("unknown_cluster_id")
                subject_key = f"unknown:{cluster if cluster is not None else event_id}"
            elif (
                event.get("probable_person_id") is not None
                and event.get("probable_person_name")
                and float(event.get("body_confidence") or 0.0) >= BODY_REID_THRESHOLD
            ):
                certainty = "probable"
                subject_key = f"person:{int(event['probable_person_id'])}"
                name = str(event["probable_person_name"])
            elif state in {"no_face", "missing_snapshot"} and self._event_age_seconds(event) < ASSISTANT_SETTLE_SECONDS:
                return
            else:
                self._mark_event(event_id, "no_greeting_candidate")
                return

        if not subject_key:
            self._mark_event(event_id, "no_subject")
            return
        # Cooldowns and first-of-turn greetings are local to each speaking camera.
        # Known and probable evidence for the same person still share one subject.
        subject_key = f"camera:{camera_id}:{subject_key}"

        timezone_name = str(event.get("timezone") or DEFAULT_TIMEZONE)
        try:
            local_now = datetime.now(ZoneInfo(timezone_name))
        except Exception:
            local_now = datetime.now(timezone.utc)
        daypart, greeting = daypart_for(local_now)
        local_date = local_now.date().isoformat()
        interval_minutes = max(1, int(event.get("interval_minutes") or DEFAULT_INTERVAL_MINUTES))

        with connection() as conn:
            turn_seen = conn.execute(
                """SELECT 1 FROM assistant_speech_log
                WHERE subject_key = ? AND local_date = ? AND daypart = ?
                  AND kind = 'turn_greeting' AND status = 'spoken'
                LIMIT 1""",
                (subject_key, local_date, daypart),
            ).fetchone()
            last = conn.execute(
                """SELECT spoken_at FROM assistant_speech_log
                WHERE subject_key = ? AND status = 'spoken'
                ORDER BY spoken_at DESC LIMIT 1""",
                (subject_key,),
            ).fetchone()

        if certainty == "unknown":
            if last and self._within_interval(str(last["spoken_at"]), interval_minutes):
                self._mark_event(event_id, "cooldown")
                return
            text = "Oi, quem é?"
            kind = "unknown_prompt"
        elif not turn_seen:
            text = greeting_message(name or "", greeting, probable=certainty == "probable")
            kind = "turn_greeting"
        else:
            if last and self._within_interval(str(last["spoken_at"]), interval_minutes):
                self._mark_event(event_id, "cooldown")
                return
            text = casual_message(name or "", probable=certainty == "probable")
            kind = "cooldown_greeting"

        try:
            self._speak_event(event, text)
            status = "spoken"
            error = None
            self.last_speech = {
                "camera_id": camera_id,
                "camera_name": event.get("camera_name"),
                "event_id": event_id,
                "text": text,
                "certainty": certainty,
                "spoken_at": utc_now(),
            }
        except Exception as exc:
            status = "error"
            error = str(exc)
            self.error = error

        with connection() as conn:
            conn.execute(
                """INSERT INTO assistant_speech_log(
                    camera_id, event_id, subject_key, certainty, kind, text,
                    local_date, daypart, status, error, spoken_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    camera_id, event_id, subject_key, certainty, kind, text,
                    local_date, daypart, status, error, utc_now(),
                ),
            )
            conn.commit()
        self._mark_event(event_id, status)

    @staticmethod
    def _within_interval(spoken_at: str, interval_minutes: int) -> bool:
        previous = _parse_iso(spoken_at)
        if previous is None:
            return False
        elapsed = (datetime.now(timezone.utc) - previous).total_seconds()
        return elapsed < interval_minutes * 60

    def _speak_event(self, event: dict[str, Any], text: str) -> None:
        if str(event.get("sync_status") or "") != "ok":
            raise RuntimeError("Câmera não está online")
        camera_id = int(event["camera_id"])
        voice_gender = str(event.get("voice_gender") or "female")
        self.speak(camera_id, text, voice_gender=voice_gender)

    def speak_test(self, camera_id: int) -> dict[str, Any]:
        settings = self.settings_for(camera_id)
        text = "Olá. O assistente desta câmera está ligado."
        self.speak(camera_id, text, voice_gender=str(settings.get("voice_gender") or "female"))
        return {"ok": True, "text": text, "voice_gender": settings.get("voice_gender")}

    def speak(self, camera_id: int, text: str, *, voice_gender: str = "female") -> None:
        if not EDGE_TTS_AVAILABLE:
            raise RuntimeError(EDGE_TTS_ERROR or "edge-tts indisponível")
        voice = VOICE_BY_GENDER.get(voice_gender, VOICE_BY_GENDER["female"])
        with connection() as conn:
            camera = conn.execute(
                "SELECT id, stream_name, rtsp_url, sync_status FROM cameras WHERE id = ? AND enabled = 1",
                (camera_id,),
            ).fetchone()
        if camera is None:
            raise LookupError("Câmera não encontrada ou desativada")
        if camera["sync_status"] != "ok":
            raise RuntimeError("Câmera não está online")

        with self.speak_lock:
            result = go2rtc.configure_talkback_stream(str(camera["stream_name"]), str(camera["rtsp_url"]))
            if not result.ok:
                raise RuntimeError(f"Talkback indisponível: {result.error or 'falha desconhecida'}")

            filename = f"tts_{camera_id}_{uuid.uuid4().hex}.mp3"
            path = ASSISTANT_AUDIO_DIR / filename
            asyncio.run(edge_tts.Communicate(text=text, voice=voice).save(str(path)))
            if not path.is_file() or path.stat().st_size < 256:
                raise RuntimeError("A síntese de voz não gerou áudio válido")

            file_url = f"http://127.0.0.1:8080/api/assistant/audio/{filename}"
            play = go2rtc.play_file_to_stream(go2rtc.talkback_stream_name(str(camera["stream_name"])), file_url)
            if not play.ok:
                raise RuntimeError(f"Não foi possível reproduzir o TTS na câmera: {play.error or 'falha desconhecida'}")

    def audio_path(self, filename: str) -> Path | None:
        if not filename or Path(filename).name != filename or not filename.lower().endswith(".mp3"):
            return None
        path = (ASSISTANT_AUDIO_DIR / filename).resolve()
        root = ASSISTANT_AUDIO_DIR.resolve()
        if root not in path.parents or not path.is_file():
            return None
        return path

    def _cleanup_audio(self) -> None:
        try:
            now = time.time()
            for path in ASSISTANT_AUDIO_DIR.glob("tts_*.mp3"):
                try:
                    if now - path.stat().st_mtime > 900:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
        except OSError:
            pass


manager = AssistantManager()

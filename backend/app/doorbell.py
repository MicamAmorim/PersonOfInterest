from __future__ import annotations

import json
import math
import struct
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import go2rtc
from .alerts import manager as alert_manager
from .assistant import manager as assistant_manager
from .assistant_talkback_guard_patch import (
    _TALKBACK_PLAYBACK_MARGIN_SECONDS,
    _TALKBACK_RELEASE_SECONDS,
    _fresh_talkback_stream,
)
from .config import ASSISTANT_AUDIO_DIR, WAKE_CONTEXT_SECONDS
from .db import connection, utc_now


DINGDONG_FILENAME = "doorbell_dingdong.wav"
DINGDONG_PATH = ASSISTANT_AUDIO_DIR / DINGDONG_FILENAME
DINGDONG_DURATION_SECONDS = 1.72


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except Exception:
        return None


def _clean_name(value: str | None) -> str:
    return " ".join(str(value or "").strip().split())[:80]


def _json_ids(raw: str | None) -> list[int]:
    try:
        values = json.loads(raw or "[]")
    except Exception:
        values = []
    output: list[int] = []
    for value in values if isinstance(values, list) else []:
        try:
            item = int(value)
        except Exception:
            continue
        if item > 0 and item not in output:
            output.append(item)
    return output


class DoorbellManager:
    def __init__(self) -> None:
        self.schema_lock = threading.Lock()
        self.audio_lock = threading.Lock()
        self._schema_ready = False

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self.schema_lock:
            if self._schema_ready:
                return
            now = utc_now()
            with connection() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS doorbell_settings (
                        id INTEGER PRIMARY KEY CHECK(id = 1),
                        target_mode TEXT NOT NULL DEFAULT 'all',
                        camera_ids_json TEXT NOT NULL DEFAULT '[]',
                        spatial_dingdong INTEGER NOT NULL DEFAULT 1,
                        spatial_voice INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS doorbell_spatial_rules (
                        rule_id INTEGER PRIMARY KEY,
                        enabled INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(rule_id) REFERENCES spatial_alert_rules(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS doorbell_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source TEXT NOT NULL,
                        source_event_id INTEGER,
                        request_name TEXT,
                        message TEXT,
                        dingdong INTEGER NOT NULL DEFAULT 0,
                        voice INTEGER NOT NULL DEFAULT 0,
                        camera_ids_json TEXT NOT NULL DEFAULT '[]',
                        status TEXT NOT NULL,
                        error TEXT,
                        created_at TEXT NOT NULL,
                        completed_at TEXT,
                        FOREIGN KEY(source_event_id) REFERENCES events(id) ON DELETE SET NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_doorbell_events_created
                        ON doorbell_events(created_at DESC);
                    """
                )
                conn.execute(
                    """INSERT OR IGNORE INTO doorbell_settings(
                        id, target_mode, camera_ids_json, spatial_dingdong,
                        spatial_voice, updated_at
                    ) VALUES (1, 'all', '[]', 1, 1, ?)""",
                    (now,),
                )
                conn.commit()
            self._schema_ready = True

    def _ensure_chime(self) -> Path:
        if DINGDONG_PATH.is_file() and DINGDONG_PATH.stat().st_size > 1000:
            return DINGDONG_PATH
        with self.audio_lock:
            if DINGDONG_PATH.is_file() and DINGDONG_PATH.stat().st_size > 1000:
                return DINGDONG_PATH
            ASSISTANT_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            sample_rate = 22050
            total = int(sample_rate * DINGDONG_DURATION_SECONDS)
            samples: list[int] = []
            notes = ((0.00, 659.25, 0.86), (0.68, 523.25, 0.82))
            for index in range(total):
                t = index / sample_rate
                value = 0.0
                for start, frequency, gain in notes:
                    local = t - start
                    if local < 0 or local > 1.05:
                        continue
                    attack = min(1.0, local / 0.018)
                    envelope = attack * math.exp(-3.6 * local)
                    value += gain * envelope * (
                        math.sin(2.0 * math.pi * frequency * local)
                        + 0.34 * math.sin(2.0 * math.pi * frequency * 2.0 * local)
                        + 0.12 * math.sin(2.0 * math.pi * frequency * 3.0 * local)
                    )
                value = max(-1.0, min(1.0, value * 0.38))
                samples.append(int(value * 32767.0))
            with wave.open(str(DINGDONG_PATH), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
        return DINGDONG_PATH

    def chime_path(self) -> Path:
        return self._ensure_chime()

    def settings(self) -> dict[str, Any]:
        self.ensure_schema()
        with connection() as conn:
            row = conn.execute("SELECT * FROM doorbell_settings WHERE id = 1").fetchone()
            cameras = conn.execute(
                "SELECT id, name, enabled, sync_status, rtsp_url FROM cameras ORDER BY name COLLATE NOCASE"
            ).fetchall()
        target_mode = str(row["target_mode"] or "all") if row else "all"
        selected_ids = _json_ids(row["camera_ids_json"] if row else None)
        camera_items: list[dict[str, Any]] = []
        for camera in cameras:
            camera_id = int(camera["id"])
            camera_items.append(
                {
                    "id": camera_id,
                    "name": str(camera["name"]),
                    "enabled": bool(camera["enabled"]),
                    "online": str(camera["sync_status"] or "") == "ok",
                    "speaker_available": bool(go2rtc.dvrip_backchannel_url(str(camera["rtsp_url"] or ""))),
                    "selected": camera_id in selected_ids,
                }
            )
        return {
            "target_mode": target_mode if target_mode in {"all", "selected"} else "all",
            "camera_ids": selected_ids,
            "spatial_dingdong": bool(row["spatial_dingdong"]) if row else True,
            "spatial_voice": bool(row["spatial_voice"]) if row else True,
            "cameras": camera_items,
        }

    def update_settings(
        self,
        *,
        target_mode: str,
        camera_ids: list[int],
        spatial_dingdong: bool,
        spatial_voice: bool,
    ) -> dict[str, Any]:
        self.ensure_schema()
        mode = str(target_mode or "all").strip().lower()
        if mode not in {"all", "selected"}:
            raise ValueError("Modo de alto-falante inválido")
        ids = list(dict.fromkeys(int(value) for value in camera_ids if int(value) > 0))
        with connection() as conn:
            if ids:
                marks = ",".join("?" for _ in ids)
                found = {
                    int(row["id"])
                    for row in conn.execute(f"SELECT id FROM cameras WHERE id IN ({marks})", ids).fetchall()
                }
                missing = [value for value in ids if value not in found]
                if missing:
                    raise LookupError(f"Câmera não encontrada: {missing[0]}")
            if mode == "selected" and not ids:
                raise ValueError("Escolha ao menos uma câmera para a campainha")
            conn.execute(
                """UPDATE doorbell_settings SET target_mode = ?, camera_ids_json = ?,
                    spatial_dingdong = ?, spatial_voice = ?, updated_at = ? WHERE id = 1""",
                (
                    mode,
                    json.dumps(ids, separators=(",", ":")),
                    int(bool(spatial_dingdong)),
                    int(bool(spatial_voice)),
                    utc_now(),
                ),
            )
            conn.commit()
        return self.settings()

    def spatial_rules(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with connection() as conn:
            rows = conn.execute(
                """SELECT sar.id rule_id, sar.name, sar.kind, sar.enabled rule_enabled,
                    c.name camera_name, COALESCE(dsr.enabled, 0) doorbell_enabled
                FROM spatial_alert_rules sar
                JOIN cameras c ON c.id = sar.camera_id
                LEFT JOIN doorbell_spatial_rules dsr ON dsr.rule_id = sar.id
                ORDER BY sar.enabled DESC, sar.name COLLATE NOCASE"""
            ).fetchall()
        return [
            {
                "rule_id": int(row["rule_id"]),
                "name": str(row["name"]),
                "kind": str(row["kind"]),
                "camera_name": str(row["camera_name"]),
                "rule_enabled": bool(row["rule_enabled"]),
                "doorbell_enabled": bool(row["doorbell_enabled"]),
            }
            for row in rows
        ]

    def set_spatial_rule(self, rule_id: int, enabled: bool) -> dict[str, Any]:
        self.ensure_schema()
        with connection() as conn:
            row = conn.execute("SELECT id FROM spatial_alert_rules WHERE id = ?", (int(rule_id),)).fetchone()
            if row is None:
                raise LookupError("Regra espacial não encontrada")
            conn.execute(
                """INSERT INTO doorbell_spatial_rules(rule_id, enabled, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at""",
                (int(rule_id), int(bool(enabled)), utc_now()),
            )
            conn.commit()
        return {"rule_id": int(rule_id), "doorbell_enabled": bool(enabled)}

    def spatial_rule_enabled(self, rule_id: int) -> bool:
        self.ensure_schema()
        with connection() as conn:
            row = conn.execute(
                "SELECT enabled FROM doorbell_spatial_rules WHERE rule_id = ?",
                (int(rule_id),),
            ).fetchone()
        return bool(row and row["enabled"])

    def _target_cameras(self) -> list[dict[str, Any]]:
        setting = self.settings()
        selected = set(int(value) for value in setting["camera_ids"])
        with connection() as conn:
            rows = conn.execute(
                "SELECT id, name, stream_name, rtsp_url, sync_status FROM cameras WHERE enabled = 1 ORDER BY id"
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            camera_id = int(row["id"])
            if setting["target_mode"] == "selected" and camera_id not in selected:
                continue
            if str(row["sync_status"] or "") != "ok":
                continue
            if not go2rtc.dvrip_backchannel_url(str(row["rtsp_url"] or "")):
                continue
            output.append(dict(row))
        return output

    def _insert_event(
        self,
        *,
        source: str,
        source_event_id: int | None,
        request_name: str,
        message: str,
        dingdong: bool,
        voice: bool,
        camera_ids: list[int],
        status: str = "queued",
        error: str | None = None,
    ) -> int:
        self.ensure_schema()
        with connection() as conn:
            cursor = conn.execute(
                """INSERT INTO doorbell_events(
                    source, source_event_id, request_name, message, dingdong, voice,
                    camera_ids_json, status, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source,
                    source_event_id,
                    request_name or None,
                    message or None,
                    int(dingdong),
                    int(voice),
                    json.dumps(camera_ids, separators=(",", ":")),
                    status,
                    error,
                    utc_now(),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def queue_ring(
        self,
        *,
        local_name: str = "",
        dingdong: bool = True,
        voice: bool = False,
        source: str = "manual",
        source_event_id: int | None = None,
        message_override: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        name = _clean_name(local_name)
        if not dingdong and not voice:
            raise ValueError("Ative o ding-dong, a mensagem de voz ou ambos")
        if voice and not name and not message_override:
            raise ValueError("Informe o nome deste aparelho para usar a mensagem de voz")
        message = str(message_override or (f"{name} chegou!" if name else "Alguém chegou!")).strip()
        targets = self._target_cameras()
        target_ids = [int(camera["id"]) for camera in targets]
        if not targets:
            event_id = self._insert_event(
                source=source,
                source_event_id=source_event_id,
                request_name=name,
                message=message,
                dingdong=dingdong,
                voice=voice,
                camera_ids=[],
                status="no_targets",
                error="Nenhum alto-falante de câmera disponível",
            )
            return {"queued": False, "event_id": event_id, "targets": [], "message": message}
        event_id = self._insert_event(
            source=source,
            source_event_id=source_event_id,
            request_name=name,
            message=message,
            dingdong=dingdong,
            voice=voice,
            camera_ids=target_ids,
        )
        threading.Thread(
            target=self._deliver_ring,
            args=(event_id, targets, bool(dingdong), bool(voice), message),
            name=f"poi-doorbell-{event_id}",
            daemon=True,
        ).start()
        return {
            "queued": True,
            "event_id": event_id,
            "targets": [{"id": int(item["id"]), "name": str(item["name"])} for item in targets],
            "message": message,
        }

    def _play_chime(self, camera: dict[str, Any]) -> None:
        self._ensure_chime()
        stream_name = str(camera["stream_name"])
        rtsp_url = str(camera["rtsp_url"])
        talkback = go2rtc.talkback_stream_name(stream_name)
        with assistant_manager.speak_lock:
            try:
                talkback = _fresh_talkback_stream(stream_name, rtsp_url)
                file_url = f"http://127.0.0.1:8080/api/doorbell/audio/{DINGDONG_FILENAME}"
                play = go2rtc.play_file_to_stream(talkback, file_url)
                if not play.ok:
                    go2rtc.delete_stream(talkback)
                    time.sleep(_TALKBACK_RELEASE_SECONDS)
                    talkback = _fresh_talkback_stream(stream_name, rtsp_url)
                    play = go2rtc.play_file_to_stream(talkback, file_url)
                if not play.ok:
                    raise RuntimeError(play.error or "Falha ao reproduzir ding-dong")
                time.sleep(DINGDONG_DURATION_SECONDS + _TALKBACK_PLAYBACK_MARGIN_SECONDS)
            finally:
                go2rtc.delete_stream(talkback)
                time.sleep(_TALKBACK_RELEASE_SECONDS)

    def _deliver_ring(
        self,
        event_id: int,
        targets: list[dict[str, Any]],
        dingdong: bool,
        voice: bool,
        message: str,
    ) -> None:
        errors: list[str] = []
        success = 0
        for camera in targets:
            try:
                if dingdong:
                    self._play_chime(camera)
                if voice:
                    settings = assistant_manager.settings_for(int(camera["id"]))
                    assistant_manager.speak(
                        int(camera["id"]),
                        message,
                        voice_gender=str(settings.get("voice_gender") or "female"),
                    )
                success += 1
            except Exception as exc:
                errors.append(f"{camera['name']}: {exc}")
        if success == len(targets):
            status = "sent"
        elif success:
            status = "partial"
        else:
            status = "error"
        with connection() as conn:
            conn.execute(
                "UPDATE doorbell_events SET status = ?, error = ?, completed_at = ? WHERE id = ?",
                (status, " | ".join(errors) or None, utc_now(), event_id),
            )
            conn.commit()

    def _identity_for_event(self, event_id: int | None) -> tuple[int | None, str | None]:
        if not event_id:
            return None, None
        with connection() as conn:
            row = conn.execute(
                """SELECT e.person_id, e.has_face, p.name,
                    EXISTS(
                        SELECT 1 FROM face_samples fs
                        WHERE fs.event_id = e.id AND fs.person_id = e.person_id
                    ) AS face_confirmed
                FROM events e
                LEFT JOIN persons p ON p.id = e.person_id
                WHERE e.id = ?""",
                (int(event_id),),
            ).fetchone()
        if row and row["person_id"] is not None and row["name"] and bool(row["has_face"]) and bool(row["face_confirmed"]):
            return int(row["person_id"]), str(row["name"])
        return None, None

    def queue_spatial_ring(self, rule_id: int, event_id: int | None) -> dict[str, Any] | None:
        if not self.spatial_rule_enabled(rule_id):
            return None
        setting = self.settings()
        dingdong = bool(setting["spatial_dingdong"])
        voice = bool(setting["spatial_voice"])
        if not dingdong and not voice:
            return None
        _, name = self._identity_for_event(event_id)
        message = f"{name} chegou!" if name else "Alguém chegou!"
        return self.queue_ring(
            local_name=name or "",
            dingdong=dingdong,
            voice=voice,
            source="spatial",
            source_event_id=event_id,
            message_override=message,
        )

    def _recent_event_for_camera(self, camera_id: int) -> dict[str, Any] | None:
        with connection() as conn:
            event_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(events)").fetchall()}
            seen_expr = "COALESCE(e.last_seen_at, e.created_at)" if "last_seen_at" in event_columns else "e.created_at"
            row = conn.execute(
                f"""SELECT e.id, e.person_id, e.has_face, e.snapshot_path,
                    {seen_expr} AS seen_at, p.name,
                    EXISTS(
                        SELECT 1 FROM face_samples fs
                        WHERE fs.event_id = e.id AND fs.person_id = e.person_id
                    ) AS face_confirmed
                FROM events e
                LEFT JOIN persons p ON p.id = e.person_id
                WHERE e.camera_id = ? AND COALESCE(e.identity_state, '') <> 'false_positive'
                ORDER BY {seen_expr} DESC LIMIT 1""",
                (int(camera_id),),
            ).fetchone()
        if row is None:
            return None
        seen = _parse_iso(str(row["seen_at"] or ""))
        if seen is None or (datetime.now(timezone.utc) - seen).total_seconds() > max(5.0, WAKE_CONTEXT_SECONDS):
            return None
        data = dict(row)
        data["identified_name"] = (
            str(row["name"])
            if row["person_id"] is not None and row["name"] and bool(row["has_face"]) and bool(row["face_confirmed"])
            else None
        )
        return data

    def queue_arrival_push(self, camera_id: int) -> dict[str, Any]:
        self.ensure_schema()
        event = self._recent_event_for_camera(camera_id)
        name = str(event.get("identified_name")) if event and event.get("identified_name") else None
        body = f"{name} chegou!" if name else "Alguém chegou!"
        event_id = int(event["id"]) if event else None
        with connection() as conn:
            count = int(conn.execute("SELECT COUNT(*) FROM push_subscriptions WHERE enabled = 1").fetchone()[0])
        if count:
            threading.Thread(
                target=self._deliver_arrival_push,
                args=(int(camera_id), event, body),
                name=f"poi-arrival-push-{camera_id}-{int(time.time())}",
                daemon=True,
            ).start()
        return {
            "queued": bool(count),
            "subscriptions": count,
            "event_id": event_id,
            "person_id": int(event["person_id"]) if event and name and event.get("person_id") is not None else None,
            "person_name": name,
            "body": body,
        }

    def _deliver_arrival_push(self, camera_id: int, event: dict[str, Any] | None, body: str) -> None:
        with connection() as conn:
            subscriptions = conn.execute(
                "SELECT * FROM push_subscriptions WHERE enabled = 1 ORDER BY id"
            ).fetchall()
        event_id = int(event["id"]) if event else None
        payload = json.dumps(
            {
                "title": "Campainha",
                "body": body,
                "url": f"/?view=timeline&event={event_id}" if event_id else "/",
                "image": f"/api/events/{event_id}/snapshot" if event_id and event and event.get("snapshot_path") else None,
                "tag": f"poi-doorbell-arrival-{camera_id}-{event_id or int(time.time())}",
                "event_id": event_id,
                "camera_id": int(camera_id),
            },
            ensure_ascii=False,
        )
        sent = 0
        failures: list[str] = []
        for subscription in subscriptions:
            status, error = alert_manager._send(subscription, payload)
            if status == "sent":
                sent += 1
            else:
                failures.append(error or status)
            if status == "gone":
                with connection() as conn:
                    conn.execute(
                        "UPDATE push_subscriptions SET enabled = 0, updated_at = ? WHERE id = ?",
                        (utc_now(), subscription["id"]),
                    )
                    conn.commit()
        self._insert_event(
            source="tonho_push",
            source_event_id=event_id,
            request_name=str(event.get("identified_name") or "") if event else "",
            message=body,
            dingdong=False,
            voice=False,
            camera_ids=[],
            status="sent" if sent and not failures else ("partial" if sent else "error"),
            error=" | ".join(failures) or None,
        )

    def list_events(self, limit: int = 30) -> list[dict[str, Any]]:
        self.ensure_schema()
        with connection() as conn:
            rows = conn.execute(
                "SELECT * FROM doorbell_events ORDER BY created_at DESC LIMIT ?",
                (max(1, min(100, int(limit))),),
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["dingdong"] = bool(item.get("dingdong"))
            item["voice"] = bool(item.get("voice"))
            item["camera_ids"] = _json_ids(item.pop("camera_ids_json", "[]"))
            output.append(item)
        return output


manager = DoorbellManager()

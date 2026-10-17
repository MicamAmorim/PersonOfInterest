from __future__ import annotations

import base64
import json
import threading
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import ALERT_POLL_SECONDS, VAPID_PRIVATE_KEY_PATH, VAPID_PUBLIC_KEY_PATH, VAPID_SUBJECT
from .db import connection, utc_now

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from pywebpush import WebPushException, webpush
    PUSH_AVAILABLE = True
    PUSH_ERROR: str | None = None
except Exception as exc:  # pragma: no cover
    serialization = None  # type: ignore
    ec = None  # type: ignore
    webpush = None  # type: ignore
    WebPushException = Exception  # type: ignore
    PUSH_AVAILABLE = False
    PUSH_ERROR = str(exc)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_clock(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)


class AlertManager:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()
        self.status = "stopped"
        self.error: str | None = None
        self.started_at = utc_now()

    @property
    def available(self) -> bool:
        return PUSH_AVAILABLE

    def ensure_vapid(self) -> str:
        if not PUSH_AVAILABLE:
            raise RuntimeError(PUSH_ERROR or "Dependências de Web Push indisponíveis")
        VAPID_PRIVATE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        if VAPID_PRIVATE_KEY_PATH.is_file() and VAPID_PUBLIC_KEY_PATH.is_file():
            return VAPID_PUBLIC_KEY_PATH.read_text(encoding="utf-8").strip()
        private_key = ec.generate_private_key(ec.SECP256R1())
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        VAPID_PRIVATE_KEY_PATH.write_bytes(pem)
        public = _b64url(public_bytes)
        VAPID_PUBLIC_KEY_PATH.write_text(public, encoding="utf-8")
        return public

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.started_at = utc_now()
            self.stop_event.clear()
            if PUSH_AVAILABLE:
                try:
                    self.ensure_vapid()
                except Exception as exc:
                    self.error = str(exc)
            self.thread = threading.Thread(target=self._run, name="poi-alerts", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=2.5)

    def state(self) -> dict[str, Any]:
        with connection() as conn:
            subscriptions = int(conn.execute("SELECT COUNT(*) FROM push_subscriptions WHERE enabled = 1").fetchone()[0])
            rules = int(conn.execute("SELECT COUNT(*) FROM alert_rules WHERE enabled = 1").fetchone()[0])
        return {
            "status": self.status,
            "error": self.error,
            "available": self.available,
            "subscriptions": subscriptions,
            "enabled_rules": rules,
        }

    def _run(self) -> None:  # pragma: no cover - background integration
        self.status = "running" if PUSH_AVAILABLE else "push_unavailable"
        while not self.stop_event.is_set():
            try:
                self.evaluate_new_events()
                if PUSH_AVAILABLE:
                    self.status = "running"
                self.error = None if PUSH_AVAILABLE else PUSH_ERROR
            except Exception as exc:
                self.status = "error"
                self.error = str(exc)
            self.stop_event.wait(max(0.3, ALERT_POLL_SECONDS))

    def evaluate_new_events(self) -> int:
        # Do not notify historical events after a restart. Identity may take a few
        # seconds, so pending events wait instead of being marked evaluated.
        with connection() as conn:
            rows = conn.execute(
                """SELECT e.*, c.name camera_name, c.location camera_location, p.name person_name
                FROM events e
                JOIN cameras c ON c.id = e.camera_id
                LEFT JOIN persons p ON p.id = e.person_id
                LEFT JOIN alert_event_state aes ON aes.event_id = e.id
                WHERE aes.event_id IS NULL AND e.created_at >= ?
                  AND COALESCE(e.identity_state, 'pending') <> 'pending'
                ORDER BY e.created_at ASC LIMIT 30""",
                (self.started_at,),
            ).fetchall()
        processed = 0
        for row in rows:
            event = dict(row)
            self._evaluate_event(event)
            with connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO alert_event_state(event_id, evaluated_at) VALUES (?, ?)",
                    (event["id"], utc_now()),
                )
                conn.commit()
            processed += 1
        return processed

    def _evaluate_event(self, event: dict[str, Any]) -> None:
        with connection() as conn:
            rules = conn.execute("SELECT * FROM alert_rules WHERE enabled = 1 ORDER BY id").fetchall()
        for rule_row in rules:
            rule = dict(rule_row)
            if not self._matches(rule, event):
                continue
            if self._cooldown_active(rule):
                continue
            self._deliver(rule, event)

    def _matches(self, rule: dict[str, Any], event: dict[str, Any]) -> bool:
        if rule.get("camera_id") is not None and int(rule["camera_id"]) != int(event["camera_id"]):
            return False
        if rule.get("unknown_only"):
            if event.get("person_id") is not None:
                return False
        elif rule.get("person_id") is not None:
            if event.get("person_id") is None or int(rule["person_id"]) != int(event["person_id"]):
                return False

        try:
            zone = ZoneInfo(rule.get("timezone") or "UTC")
        except Exception:
            zone = timezone.utc
        local = _parse_iso(event["created_at"]).astimezone(zone)
        try:
            weekdays = json.loads(rule.get("weekdays_json") or "[0,1,2,3,4,5,6]")
        except Exception:
            weekdays = list(range(7))
        if local.weekday() not in {int(day) for day in weekdays}:
            return False

        start = _parse_clock(rule.get("start_time"))
        end = _parse_clock(rule.get("end_time"))
        if start and end:
            minute = local.hour * 60 + local.minute
            start_min = start[0] * 60 + start[1]
            end_min = end[0] * 60 + end[1]
            if start_min <= end_min:
                if not (start_min <= minute <= end_min):
                    return False
            else:  # Crosses midnight, e.g. 23:00-06:00.
                if not (minute >= start_min or minute <= end_min):
                    return False
        return True

    def _cooldown_active(self, rule: dict[str, Any]) -> bool:
        cooldown = max(0, int(rule.get("cooldown_seconds") or 0))
        if cooldown <= 0:
            return False
        with connection() as conn:
            row = conn.execute(
                """SELECT created_at FROM alert_deliveries
                WHERE rule_id = ? AND status = 'sent'
                ORDER BY created_at DESC LIMIT 1""",
                (rule["id"],),
            ).fetchone()
        if not row:
            return False
        return (datetime.now(timezone.utc) - _parse_iso(row["created_at"])).total_seconds() < cooldown

    def _deliver(self, rule: dict[str, Any], event: dict[str, Any]) -> None:
        with connection() as conn:
            subscriptions = conn.execute(
                "SELECT * FROM push_subscriptions WHERE enabled = 1 ORDER BY id"
            ).fetchall()
        identity = event.get("person_name") or "Pessoa desconhecida"
        camera = event.get("camera_name") or "Câmera"
        body = f"{identity} detectada em {camera}."
        payload = json.dumps(
            {
                "title": rule.get("name") or "PersonOfInterest",
                "body": body,
                "url": f"/?view=timeline&event={event['id']}",
                "tag": f"poi-rule-{rule['id']}",
                "event_id": event["id"],
                "camera_id": event["camera_id"],
            },
            ensure_ascii=False,
        )
        if not subscriptions:
            # A rule can exist before a phone subscribes. Record that it matched,
            # but don't start cooldown without an actual delivery.
            return
        for subscription in subscriptions:
            status, error = self._send(subscription, payload)
            with connection() as conn:
                conn.execute(
                    """INSERT INTO alert_deliveries(rule_id, event_id, subscription_id, status, error, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (rule["id"], event["id"], subscription["id"], status, error, utc_now()),
                )
                if status == "gone":
                    conn.execute("UPDATE push_subscriptions SET enabled = 0, updated_at = ? WHERE id = ?", (utc_now(), subscription["id"]))
                conn.commit()

    def _send(self, subscription: Any, payload: str) -> tuple[str, str | None]:
        if not PUSH_AVAILABLE:
            return "error", PUSH_ERROR or "Web Push indisponível"
        info = {
            "endpoint": subscription["endpoint"],
            "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
        }
        try:
            webpush(
                subscription_info=info,
                data=payload,
                vapid_private_key=str(VAPID_PRIVATE_KEY_PATH),
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=120,
            )
            return "sent", None
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (404, 410):
                return "gone", str(exc)
            return "error", str(exc)
        except Exception as exc:
            return "error", str(exc)

    def test_push(self) -> dict[str, int]:
        with connection() as conn:
            subscriptions = conn.execute("SELECT * FROM push_subscriptions WHERE enabled = 1").fetchall()
        payload = json.dumps(
            {
                "title": "PersonOfInterest",
                "body": "Notificações Web Push estão funcionando.",
                "url": "/",
                "tag": "poi-test",
            },
            ensure_ascii=False,
        )
        sent = 0
        failed = 0
        for subscription in subscriptions:
            status, _ = self._send(subscription, payload)
            if status == "sent":
                sent += 1
            else:
                failed += 1
        return {"sent": sent, "failed": failed}


manager = AlertManager()

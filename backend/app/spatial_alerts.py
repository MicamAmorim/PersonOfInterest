from __future__ import annotations

import json
import math
import threading
import time
from typing import Any

from .alerts import manager as alert_manager
from .db import connection, utc_now


Point = tuple[float, float]
_EPS = 1e-9
_MIN_CROSS_MOVE = 0.006
_RULE_CACHE_SECONDS = 1.0
_TRACK_FORGET_SECONDS = 6.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _point(raw: Any) -> Point:
    return (_clamp01(float(raw.get("x", 0.0))), _clamp01(float(raw.get("y", 0.0))))


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Point, b: Point, p: Point) -> bool:
    return (
        min(a[0], b[0]) - _EPS <= p[0] <= max(a[0], b[0]) + _EPS
        and min(a[1], b[1]) - _EPS <= p[1] <= max(a[1], b[1]) + _EPS
        and abs(_cross(a, b, p)) <= 1e-8
    )


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1 = _cross(a, b, c)
    o2 = _cross(a, b, d)
    o3 = _cross(c, d, a)
    o4 = _cross(c, d, b)
    if ((o1 > _EPS and o2 < -_EPS) or (o1 < -_EPS and o2 > _EPS)) and (
        (o3 > _EPS and o4 < -_EPS) or (o3 < -_EPS and o4 > _EPS)
    ):
        return True
    return (
        (abs(o1) <= _EPS and _on_segment(a, b, c))
        or (abs(o2) <= _EPS and _on_segment(a, b, d))
        or (abs(o3) <= _EPS and _on_segment(c, d, a))
        or (abs(o4) <= _EPS and _on_segment(c, d, b))
    )


def _crosses_polyline(previous: Point, current: Point, points: list[Point]) -> bool:
    if len(points) < 2:
        return False
    return any(
        _segments_intersect(previous, current, points[index], points[index + 1])
        for index in range(len(points) - 1)
    )


def _movement_matches_arrow(previous: Point, current: Point, arrow_from: Point, arrow_to: Point) -> bool:
    mx, my = current[0] - previous[0], current[1] - previous[1]
    ax, ay = arrow_to[0] - arrow_from[0], arrow_to[1] - arrow_from[1]
    movement = math.hypot(mx, my)
    arrow = math.hypot(ax, ay)
    if movement < _MIN_CROSS_MOVE or arrow < _MIN_CROSS_MOVE:
        return False
    cosine = (mx * ax + my * ay) / max(_EPS, movement * arrow)
    return cosine > 0.20


def _inside_polygon(point: Point, polygon: list[Point]) -> bool:
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if _on_segment((xi, yi), (xj, yj), point):
            return True
        denominator = yj - yi
        if abs(denominator) < _EPS:
            denominator = _EPS if denominator >= 0 else -_EPS
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / denominator + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _parse_geometry(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


class SpatialAlertManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        self._track_state: dict[tuple[int, int, int], dict[str, Any]] = {}
        self._rules_cache: dict[int, list[dict[str, Any]]] = {}
        self._rules_cache_at: dict[int, float] = {}
        self.last_trigger: dict[str, Any] | None = None
        self.error: str | None = None

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with connection() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS spatial_alert_rules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        camera_id INTEGER NOT NULL,
                        kind TEXT NOT NULL,
                        geometry_json TEXT NOT NULL,
                        zone_mode TEXT,
                        dwell_seconds REAL NOT NULL DEFAULT 0,
                        cooldown_seconds REAL NOT NULL DEFAULT 30,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_spatial_rules_camera_enabled
                        ON spatial_alert_rules(camera_id, enabled);

                    CREATE TABLE IF NOT EXISTS spatial_alert_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        rule_id INTEGER NOT NULL,
                        camera_id INTEGER NOT NULL,
                        track_id INTEGER,
                        event_id INTEGER,
                        trigger_kind TEXT NOT NULL,
                        foot_x REAL NOT NULL,
                        foot_y REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(rule_id) REFERENCES spatial_alert_rules(id) ON DELETE CASCADE,
                        FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE,
                        FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE SET NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_spatial_events_created
                        ON spatial_alert_events(created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_spatial_events_rule_created
                        ON spatial_alert_events(rule_id, created_at DESC);
                    """
                )
                conn.commit()
            self._schema_ready = True

    def notify_change(self, camera_id: int | None = None) -> None:
        with self.lock:
            if camera_id is None:
                self._rules_cache.clear()
                self._rules_cache_at.clear()
            else:
                self._rules_cache.pop(int(camera_id), None)
                self._rules_cache_at.pop(int(camera_id), None)
            self._track_state.clear()

    def _rules_for(self, camera_id: int) -> list[dict[str, Any]]:
        self.ensure_schema()
        now = time.monotonic()
        with self.lock:
            cached = self._rules_cache.get(camera_id)
            cached_at = float(self._rules_cache_at.get(camera_id, 0.0))
            if cached is not None and now - cached_at < _RULE_CACHE_SECONDS:
                return cached
        with connection() as conn:
            rows = conn.execute(
                """SELECT * FROM spatial_alert_rules
                WHERE enabled = 1 AND camera_id = ? ORDER BY id""",
                (camera_id,),
            ).fetchall()
        rules = [dict(row) for row in rows]
        with self.lock:
            self._rules_cache[camera_id] = rules
            self._rules_cache_at[camera_id] = now
        return rules

    @staticmethod
    def _foot(track: Any, width: int, height: int) -> Point:
        x, y, w, h = track.bbox
        return (
            _clamp01((float(x) + float(w) / 2.0) / max(1.0, float(width))),
            _clamp01((float(y) + float(h)) / max(1.0, float(height))),
        )

    def process_tracks(
        self,
        camera_id: int,
        camera_name: str,
        width: int,
        height: int,
        tracks: list[Any],
    ) -> None:
        if width <= 0 or height <= 0:
            return
        try:
            rules = self._rules_for(int(camera_id))
            if not rules:
                return
            now = time.monotonic()
            seen_keys: set[tuple[int, int, int]] = set()
            for track in tracks:
                if int(getattr(track, "missed", 0)) != 0 or int(getattr(track, "hits", 0)) < 2:
                    continue
                foot = self._foot(track, width, height)
                track_id = int(track.id)
                for rule in rules:
                    rule_id = int(rule["id"])
                    key = (int(camera_id), rule_id, track_id)
                    seen_keys.add(key)
                    with self.lock:
                        state = self._track_state.setdefault(
                            key,
                            {
                                "previous": None,
                                "condition_since": None,
                                "fired": False,
                                "last_trigger": 0.0,
                                "last_seen": now,
                            },
                        )
                        state["last_seen"] = now
                    kind = str(rule.get("kind") or "")
                    geometry = _parse_geometry(rule.get("geometry_json"))
                    if kind == "line_cross":
                        self._process_line(rule, state, track, camera_id, camera_name, foot, geometry, now)
                    elif kind == "zone_dwell":
                        self._process_zone(rule, state, track, camera_id, camera_name, foot, geometry, now)
                    with self.lock:
                        state["previous"] = foot

            with self.lock:
                stale = [
                    key for key, value in self._track_state.items()
                    if key[0] == int(camera_id)
                    and key not in seen_keys
                    and now - float(value.get("last_seen", 0.0)) > _TRACK_FORGET_SECONDS
                ]
                for key in stale:
                    self._track_state.pop(key, None)
            self.error = None
        except Exception as exc:
            self.error = str(exc)

    def _cooldown_ok(self, rule: dict[str, Any], state: dict[str, Any], now: float) -> bool:
        cooldown = max(0.0, float(rule.get("cooldown_seconds") or 0.0))
        return now - float(state.get("last_trigger") or 0.0) >= cooldown

    def _process_line(
        self,
        rule: dict[str, Any],
        state: dict[str, Any],
        track: Any,
        camera_id: int,
        camera_name: str,
        foot: Point,
        geometry: dict[str, Any],
        now: float,
    ) -> None:
        previous = state.get("previous")
        if previous is None:
            return
        try:
            points = [_point(item) for item in geometry.get("points", [])]
            arrow = geometry.get("arrow") or {}
            arrow_from = _point(arrow.get("from") or {})
            arrow_to = _point(arrow.get("to") or {})
        except Exception:
            return
        if not _crosses_polyline(previous, foot, points):
            return
        if not _movement_matches_arrow(previous, foot, arrow_from, arrow_to):
            return
        if not self._cooldown_ok(rule, state, now):
            return
        state["last_trigger"] = now
        self._trigger(rule, track, camera_id, camera_name, foot, "line_cross")

    def _process_zone(
        self,
        rule: dict[str, Any],
        state: dict[str, Any],
        track: Any,
        camera_id: int,
        camera_name: str,
        foot: Point,
        geometry: dict[str, Any],
        now: float,
    ) -> None:
        try:
            polygon = [_point(item) for item in geometry.get("points", [])]
        except Exception:
            return
        inside = _inside_polygon(foot, polygon)
        mode = str(rule.get("zone_mode") or "inside")
        condition = inside if mode == "inside" else not inside
        if not condition:
            state["condition_since"] = None
            state["fired"] = False
            return
        if state.get("condition_since") is None:
            state["condition_since"] = now
            return
        dwell = max(0.0, float(rule.get("dwell_seconds") or 0.0))
        if state.get("fired") or now - float(state["condition_since"]) < dwell:
            return
        if not self._cooldown_ok(rule, state, now):
            return
        state["fired"] = True
        state["last_trigger"] = now
        self._trigger(rule, track, camera_id, camera_name, foot, f"zone_{mode}")

    def _identity_label(self, event_id: int | None) -> str:
        if not event_id:
            return "Pessoa"
        with connection() as conn:
            row = conn.execute(
                """SELECT p.name person_name, pp.name probable_name
                FROM events e
                LEFT JOIN persons p ON p.id = e.person_id
                LEFT JOIN persons pp ON pp.id = e.probable_person_id
                WHERE e.id = ?""",
                (event_id,),
            ).fetchone()
        if not row:
            return "Pessoa"
        if row["person_name"]:
            return str(row["person_name"])
        if row["probable_name"]:
            return f"Provável {row['probable_name']}"
        return "Pessoa"

    def _trigger(
        self,
        rule: dict[str, Any],
        track: Any,
        camera_id: int,
        camera_name: str,
        foot: Point,
        trigger_kind: str,
    ) -> None:
        self.ensure_schema()
        event_id = int(track.event_id) if getattr(track, "event_id", None) else None
        now = utc_now()
        with connection() as conn:
            cursor = conn.execute(
                """INSERT INTO spatial_alert_events(
                    rule_id, camera_id, track_id, event_id, trigger_kind,
                    foot_x, foot_y, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(rule["id"]), int(camera_id), int(track.id), event_id,
                    trigger_kind, float(foot[0]), float(foot[1]), now,
                ),
            )
            conn.commit()
            spatial_event_id = int(cursor.lastrowid)

        self.last_trigger = {
            "id": spatial_event_id,
            "rule_id": int(rule["id"]),
            "rule_name": str(rule.get("name") or "Cerca virtual"),
            "camera_id": int(camera_id),
            "camera_name": camera_name,
            "track_id": int(track.id),
            "event_id": event_id,
            "trigger_kind": trigger_kind,
            "foot": {"x": round(foot[0], 4), "y": round(foot[1], 4)},
            "created_at": now,
        }
        threading.Thread(
            target=self._deliver,
            args=(dict(rule), int(camera_id), camera_name, event_id, trigger_kind),
            name=f"poi-spatial-push-{rule['id']}-{track.id}",
            daemon=True,
        ).start()

    def _deliver(
        self,
        rule: dict[str, Any],
        camera_id: int,
        camera_name: str,
        event_id: int | None,
        trigger_kind: str,
    ) -> None:
        try:
            who = self._identity_label(event_id)
            rule_name = str(rule.get("name") or "Cerca virtual")
            if trigger_kind == "line_cross":
                body = f"{who} cruzou {rule_name} em {camera_name} na direção configurada."
            elif trigger_kind == "zone_inside":
                body = f"{who} permaneceu dentro de {rule_name} em {camera_name}."
            else:
                body = f"{who} permaneceu fora de {rule_name} em {camera_name}."
            payload = json.dumps(
                {
                    "title": rule_name,
                    "body": body,
                    "url": f"/?view=timeline&event={event_id}" if event_id else "/?view=alerts",
                    "image": f"/api/events/{event_id}/snapshot" if event_id else None,
                    "tag": f"poi-spatial-{rule['id']}",
                    "event_id": event_id,
                    "camera_id": camera_id,
                    "spatial_rule_id": int(rule["id"]),
                    "trigger_kind": trigger_kind,
                },
                ensure_ascii=False,
            )
            with connection() as conn:
                subscriptions = conn.execute(
                    "SELECT * FROM push_subscriptions WHERE enabled = 1 ORDER BY id"
                ).fetchall()
            for subscription in subscriptions:
                status, _ = alert_manager._send(subscription, payload)
                if status == "gone":
                    with connection() as conn:
                        conn.execute(
                            "UPDATE push_subscriptions SET enabled = 0, updated_at = ? WHERE id = ?",
                            (utc_now(), subscription["id"]),
                        )
                        conn.commit()
        except Exception as exc:
            self.error = f"Push espacial: {exc}"

    def state(self) -> dict[str, Any]:
        self.ensure_schema()
        with connection() as conn:
            enabled = int(conn.execute(
                "SELECT COUNT(*) FROM spatial_alert_rules WHERE enabled = 1"
            ).fetchone()[0])
        with self.lock:
            active_states = len(self._track_state)
        return {
            "enabled_rules": enabled,
            "active_track_states": active_states,
            "last_trigger": self.last_trigger,
            "error": self.error,
            "analysis_point": "bbox_bottom_center",
        }


manager = SpatialAlertManager()

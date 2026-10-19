from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

from .db import connection

_INSTALLED = False


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        raw = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _duration_seconds(row) -> float | None:
    start = _parse_dt(row["created_at"])
    end = _parse_dt(row["ended_at"] or row["last_seen_at"])
    if not start or not end:
        return None
    value = (end - start).total_seconds()
    if value < 0 or value > 6 * 3600:
        return None
    return value


def _weekday_label(index: int) -> str:
    return ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")[index]


def _date_label(dt: datetime) -> str:
    return dt.strftime("%d/%m")


def analytics_overview(days: int = 30, tz: str = "UTC") -> dict:
    days = max(1, min(365, int(days or 30)))
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = timezone.utc
        tz = "UTC"

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=days)

    with connection() as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.camera_id, e.track_id, e.person_id, e.probable_person_id,
                   e.unknown_cluster_id, e.identity_state, e.created_at, e.last_seen_at,
                   e.ended_at, e.observation_count,
                   c.name AS camera_name,
                   p.name AS person_name,
                   pp.name AS probable_person_name
            FROM events e
            JOIN cameras c ON c.id = e.camera_id
            LEFT JOIN persons p ON p.id = e.person_id
            LEFT JOIN persons pp ON pp.id = e.probable_person_id
            WHERE e.created_at >= ?
              AND COALESCE(e.identity_state, '') <> 'false_positive'
              AND COALESCE(e.event_type, 'person') = 'person'
            ORDER BY e.created_at ASC
            """,
            (cutoff.isoformat(),),
        ).fetchall()

    parsed: list[dict] = []
    durations: list[float] = []
    by_day = defaultdict(lambda: {"total": 0, "known": 0, "probable": 0, "unknown": 0})
    by_hour = defaultdict(lambda: {"total": 0, "known": 0, "probable": 0, "unknown": 0})
    heat = Counter()
    camera_stats = defaultdict(lambda: {"count": 0, "known": 0, "probable": 0, "unknown": 0})
    person_stats = defaultdict(lambda: {"count": 0, "days": set(), "hours": Counter(), "weekdays": Counter(), "last_seen": None})
    unknown_clusters = Counter()

    known = probable = unknown = 0

    for row in rows:
        created = _parse_dt(row["created_at"])
        if not created:
            continue
        local = created.astimezone(zone)
        if row["person_id"] is not None:
            kind = "known"
            known += 1
        elif row["probable_person_id"] is not None:
            kind = "probable"
            probable += 1
        else:
            kind = "unknown"
            unknown += 1

        day_key = local.date().isoformat()
        by_day[day_key]["total"] += 1
        by_day[day_key][kind] += 1
        by_hour[local.hour]["total"] += 1
        by_hour[local.hour][kind] += 1
        heat[(local.weekday(), local.hour)] += 1

        cam = camera_stats[int(row["camera_id"])]
        cam["name"] = str(row["camera_name"])
        cam["count"] += 1
        cam[kind] += 1

        if row["person_id"] is not None:
            pid = int(row["person_id"])
            stat = person_stats[pid]
            stat["name"] = str(row["person_name"] or f"Pessoa {pid}")
            stat["count"] += 1
            stat["days"].add(day_key)
            stat["hours"][local.hour] += 1
            stat["weekdays"][local.weekday()] += 1
            stat["last_seen"] = local.isoformat()

        if row["unknown_cluster_id"] is not None and row["person_id"] is None:
            unknown_clusters[int(row["unknown_cluster_id"])] += 1

        duration = _duration_seconds(row)
        if duration is not None:
            durations.append(duration)

        parsed.append({
            "person_id": int(row["person_id"]) if row["person_id"] is not None else None,
            "camera_id": int(row["camera_id"]),
            "camera_name": str(row["camera_name"]),
            "created": created,
        })

    daily = []
    for offset in range(days - 1, -1, -1):
        dt = (now_utc.astimezone(zone) - timedelta(days=offset))
        key = dt.date().isoformat()
        item = by_day[key]
        daily.append({"date": key, "label": _date_label(dt), **item})

    hourly = []
    for hour in range(24):
        item = by_hour[hour]
        hourly.append({"hour": hour, "label": f"{hour:02d}h", **item})

    heat_cells = [
        {"weekday": weekday, "hour": hour, "count": int(heat[(weekday, hour)])}
        for weekday in range(7)
        for hour in range(24)
    ]
    heat_max = max((cell["count"] for cell in heat_cells), default=0)

    cameras = sorted(
        ({"camera_id": cid, **value} for cid, value in camera_stats.items()),
        key=lambda item: (-item["count"], item["name"].lower()),
    )

    people = []
    routines = []
    for pid, stat in person_stats.items():
        common_hour = stat["hours"].most_common(1)[0] if stat["hours"] else (None, 0)
        common_days = stat["weekdays"].most_common(2)
        person = {
            "person_id": pid,
            "name": stat["name"],
            "count": int(stat["count"]),
            "active_days": len(stat["days"]),
            "last_seen": stat["last_seen"],
            "typical_hour": common_hour[0],
        }
        people.append(person)
        if stat["count"] >= 3:
            reliability = common_hour[1] / max(1, stat["count"])
            routines.append({
                **person,
                "typical_hour_label": f"{common_hour[0]:02d}:00–{(common_hour[0] + 1) % 24:02d}:00" if common_hour[0] is not None else None,
                "strong_weekdays": [_weekday_label(index) for index, _count in common_days],
                "concentration": round(reliability, 3),
            })
    people.sort(key=lambda item: (-item["count"], item["name"].lower()))
    routines.sort(key=lambda item: (-item["count"], -item["concentration"]))

    transitions = Counter()
    events_by_person = defaultdict(list)
    for item in parsed:
        if item["person_id"] is not None:
            events_by_person[item["person_id"]].append(item)
    for _pid, items in events_by_person.items():
        items.sort(key=lambda item: item["created"])
        for previous, current in zip(items, items[1:]):
            gap = (current["created"] - previous["created"]).total_seconds()
            if 0 <= gap <= 30 * 60 and previous["camera_id"] != current["camera_id"]:
                transitions[(previous["camera_name"], current["camera_name"])] += 1
    transition_rows = [
        {"from": source, "to": target, "count": count}
        for (source, target), count in transitions.most_common(12)
    ]

    duration_buckets = [
        {"label": "< 5 s", "count": 0},
        {"label": "5–15 s", "count": 0},
        {"label": "15–30 s", "count": 0},
        {"label": "30–60 s", "count": 0},
        {"label": "1–3 min", "count": 0},
        {"label": "> 3 min", "count": 0},
    ]
    for value in durations:
        if value < 5:
            index = 0
        elif value < 15:
            index = 1
        elif value < 30:
            index = 2
        elif value < 60:
            index = 3
        elif value < 180:
            index = 4
        else:
            index = 5
        duration_buckets[index]["count"] += 1

    peak_hour = max(hourly, key=lambda item: item["total"], default={"hour": 0, "total": 0})
    weekday_totals = Counter()
    for (weekday, _hour), count in heat.items():
        weekday_totals[weekday] += count
    busiest_weekday = weekday_totals.most_common(1)[0] if weekday_totals else (None, 0)

    return {
        "window_days": days,
        "timezone": tz,
        "generated_at": now_utc.isoformat(),
        "summary": {
            "events": len(parsed),
            "known": known,
            "probable": probable,
            "unknown": unknown,
            "unique_known": len(person_stats),
            "recurring_unknowns": sum(1 for count in unknown_clusters.values() if count >= 2),
            "avg_duration_seconds": round(sum(durations) / len(durations), 1) if durations else None,
            "median_duration_seconds": round(float(median(durations)), 1) if durations else None,
            "peak_hour": int(peak_hour["hour"]) if peak_hour["total"] else None,
            "busiest_weekday": _weekday_label(busiest_weekday[0]) if busiest_weekday[0] is not None else None,
        },
        "daily": daily,
        "hourly": hourly,
        "heatmap": {
            "weekdays": [_weekday_label(i) for i in range(7)],
            "max": heat_max,
            "cells": heat_cells,
        },
        "cameras": cameras,
        "people": people[:20],
        "routines": routines[:12],
        "transitions": transition_rows,
        "duration_buckets": duration_buckets,
    }


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from .api_v34 import router

    router.add_api_route(
        "/api/analytics/overview",
        analytics_overview,
        methods=["GET"],
        tags=["analytics"],
    )
    _INSTALLED = True

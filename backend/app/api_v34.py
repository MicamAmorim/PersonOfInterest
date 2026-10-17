from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import websockets
from fastapi import APIRouter, HTTPException, Query, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse

from . import go2rtc
from .alerts import manager as alert_manager
from .body_identity import manager as body_identity_manager
from .config import FACES_DIR, GO2RTC_API_URL
from .db import connection, utc_now
from .identity import manager as identity_manager
from .models import AlertRuleCreate, AlertRuleUpdate, IdentityAssignRequest, PushSubscriptionRequest


router = APIRouter()


def _camera_row(camera_id: int):
    with connection() as conn:
        row = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")
    return row


async def _bridge_websocket(websocket: WebSocket, upstream_url: str) -> None:
    await websocket.accept()
    try:
        async with websockets.connect(upstream_url, max_size=None) as upstream:
            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        return
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@router.websocket("/api/cameras/{camera_id}/webrtc/ws")
async def camera_webrtc_proxy(websocket: WebSocket, camera_id: int) -> None:
    """Same-origin go2rtc signaling for camera audio and isolated talkback."""
    with connection() as conn:
        row = conn.execute(
            "SELECT stream_name, rtsp_url FROM cameras WHERE id = ? AND enabled = 1",
            (camera_id,),
        ).fetchone()
    if row is None:
        await websocket.close(code=4404)
        return

    use_talkback = (websocket.query_params.get("talkback") or "") == "1"
    stream_name = str(row["stream_name"])
    if use_talkback:
        result = await asyncio.to_thread(
            go2rtc.configure_talkback_stream,
            stream_name,
            str(row["rtsp_url"]),
        )
        if not result.ok:
            await websocket.accept()
            await websocket.send_text(json.dumps({
                "type": "error",
                "value": f"Talkback DVRIP indisponível: {result.error or 'falha desconhecida'}",
            }))
            await websocket.close(code=1011)
            return
        stream_name = go2rtc.talkback_stream_name(stream_name)

    upstream_url = f"ws://127.0.0.1:1984/api/ws?src={quote(stream_name)}"
    await _bridge_websocket(websocket, upstream_url)


_GO2RTC_PLAYER_ASSETS = {
    "stream.html": "text/html; charset=utf-8",
    "video-stream.js": "application/javascript; charset=utf-8",
    "video-rtc.js": "application/javascript; charset=utf-8",
}


def _read_go2rtc_asset(asset_name: str) -> bytes:
    url = f"{GO2RTC_API_URL}/{asset_name}"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=4.0) as response:
        return response.read()


@router.get("/go2rtc/{asset_name}", include_in_schema=False)
async def go2rtc_player_asset(asset_name: str) -> Response:
    """Expose only go2rtc's universal player assets through the app origin."""
    content_type = _GO2RTC_PLAYER_ASSETS.get(asset_name)
    if content_type is None:
        raise HTTPException(status_code=404, detail="Recurso go2rtc não permitido")
    try:
        body = await asyncio.to_thread(_read_go2rtc_asset, asset_name)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"go2rtc indisponível: {exc}") from exc
    return Response(content=body, headers={"Content-Type": content_type, "Cache-Control": "no-cache"})


@router.websocket("/go2rtc/api/ws")
async def go2rtc_stream_proxy(websocket: WebSocket) -> None:
    src = (websocket.query_params.get("src") or "").strip()
    if not src:
        await websocket.close(code=4400)
        return
    with connection() as conn:
        row = conn.execute(
            "SELECT stream_name FROM cameras WHERE stream_name = ? AND enabled = 1",
            (src,),
        ).fetchone()
    if row is None:
        await websocket.close(code=4404)
        return
    upstream_url = f"ws://127.0.0.1:1984/api/ws?src={quote(src)}"
    await _bridge_websocket(websocket, upstream_url)


# ------------------------------- V3 identity -------------------------------


@router.get("/api/identity/status")
def identity_status() -> dict:
    state = identity_manager.state()
    state["body_reid"] = body_identity_manager.state()
    return state


@router.get("/api/identity/clusters")
def identity_clusters() -> list[dict]:
    return identity_manager.list_clusters()


@router.get("/api/identity/clusters/{cluster_id}/face")
def identity_cluster_face(cluster_id: int) -> FileResponse:
    path = identity_manager.cluster_face_path(cluster_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Imagem de rosto não encontrada")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.post("/api/identity/clusters/{cluster_id}/assign")
def assign_identity_cluster(cluster_id: int, payload: IdentityAssignRequest) -> dict:
    try:
        result = identity_manager.assign_cluster(cluster_id, person_id=payload.person_id, name=payload.name)
        body_identity_manager.notify_change()
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/identity/events/{event_id}/assign")
def assign_identity_event(event_id: int, payload: IdentityAssignRequest) -> dict:
    """Manual identity correction/confirmation from the timeline.

    Manual confirmation is absolute because it comes from the user. If a face
    sample exists it is reassigned to the chosen person; the body crop becomes a
    verified ReID reference too, but body-only future matches remain "Provável".
    """
    try:
        result = identity_manager.assign_event(event_id, person_id=payload.person_id, name=payload.name)
        body_identity_manager.confirm_event_identity(event_id, int(result["person_id"]))
        body_identity_manager.notify_change()
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/identity/reindex")
def identity_reindex(include_no_face: bool = False) -> dict:
    result = identity_manager.reindex(include_no_face=include_no_face)
    body_identity_manager.notify_change()
    return result


def _delete_face_crop(relative: str | None) -> None:
    if not relative:
        return
    path = (FACES_DIR / relative).resolve()
    root = FACES_DIR.resolve()
    if root not in path.parents:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@router.patch("/api/events/{event_id}/false-positive")
def set_event_false_positive(event_id: int, value: bool = Query(...)) -> dict:
    """Mark/unmark a detection as a false positive.

    Face/body identity evidence is removed. The OSNet appearance embedding is
    retained separately as a hard-negative sample for future detector tuning;
    it is never used as a positive identity reference.
    """
    crops_to_delete: set[str] = set()
    with connection() as conn:
        event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Evento não encontrado")

        if value:
            sample = conn.execute(
                "SELECT cluster_id, crop_path FROM face_samples WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            cluster_id = event["unknown_cluster_id"] or (sample["cluster_id"] if sample else None)

            if cluster_id is not None:
                samples = conn.execute(
                    "SELECT event_id, crop_path FROM face_samples WHERE cluster_id = ?",
                    (cluster_id,),
                ).fetchall()
                crops_to_delete.update(str(row["crop_path"]) for row in samples if row["crop_path"])
                conn.execute("DELETE FROM face_samples WHERE cluster_id = ?", (cluster_id,))
                conn.execute(
                    """UPDATE events
                    SET person_id = NULL, probable_person_id = NULL, body_confidence = NULL,
                        body_identity_source = NULL, unknown_cluster_id = NULL,
                        identity_state = 'pending', identity_confidence = NULL
                    WHERE unknown_cluster_id = ? AND id <> ?
                      AND COALESCE(identity_state, '') <> 'false_positive'""",
                    (cluster_id, event_id),
                )
                conn.execute("DELETE FROM unknown_clusters WHERE id = ?", (cluster_id,))

            current_sample = conn.execute(
                "SELECT crop_path FROM face_samples WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if current_sample and current_sample["crop_path"]:
                crops_to_delete.add(str(current_sample["crop_path"]))
            conn.execute("DELETE FROM face_samples WHERE event_id = ?", (event_id,))
            conn.execute(
                """UPDATE events
                SET person_id = NULL, probable_person_id = NULL, body_confidence = NULL,
                    body_identity_source = NULL, unknown_cluster_id = NULL,
                    identity_state = 'false_positive', identity_confidence = NULL
                WHERE id = ?""",
                (event_id,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO alert_event_state(event_id, evaluated_at) VALUES (?, ?)",
                (event_id, utc_now()),
            )
        else:
            current_sample = conn.execute(
                "SELECT crop_path FROM face_samples WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if current_sample and current_sample["crop_path"]:
                crops_to_delete.add(str(current_sample["crop_path"]))
            conn.execute("DELETE FROM face_samples WHERE event_id = ?", (event_id,))
            conn.execute(
                """UPDATE events
                SET person_id = NULL, probable_person_id = NULL, body_confidence = NULL,
                    body_identity_source = NULL, unknown_cluster_id = NULL,
                    identity_state = 'pending', identity_confidence = NULL
                WHERE id = ?""",
                (event_id,),
            )
            conn.execute("DELETE FROM alert_event_state WHERE event_id = ?", (event_id,))
        conn.commit()

    if value:
        body_identity_manager.record_false_positive(event_id)
    else:
        body_identity_manager.undo_false_positive(event_id)

    for crop in crops_to_delete:
        _delete_face_crop(crop)

    return {
        "ok": True,
        "event_id": event_id,
        "is_false_positive": bool(value),
        "identity_state": "false_positive" if value else "pending",
    }


# ------------------------------- V4 Web Push -------------------------------


@router.get("/api/push/status")
def push_status() -> dict:
    state = alert_manager.state()
    try:
        state["vapid_public_key"] = alert_manager.ensure_vapid() if alert_manager.available else None
    except Exception as exc:
        state["vapid_public_key"] = None
        state["error"] = str(exc)
    return state


@router.get("/api/push/vapid-public-key")
def vapid_public_key() -> dict:
    try:
        return {"public_key": alert_manager.ensure_vapid()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/push/subscriptions", status_code=status.HTTP_201_CREATED)
def save_push_subscription(payload: PushSubscriptionRequest) -> dict:
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """INSERT INTO push_subscriptions(endpoint, p256dh, auth, expiration_time, user_agent, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                p256dh = excluded.p256dh,
                auth = excluded.auth,
                expiration_time = excluded.expiration_time,
                user_agent = excluded.user_agent,
                enabled = 1,
                updated_at = excluded.updated_at""",
            (payload.endpoint, payload.p256dh, payload.auth, payload.expiration_time, payload.user_agent, now, now),
        )
        row = conn.execute("SELECT id FROM push_subscriptions WHERE endpoint = ?", (payload.endpoint,)).fetchone()
        conn.commit()
    return {"ok": True, "id": int(row["id"])}


@router.delete("/api/push/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def disable_push_subscription(endpoint: str = Query(min_length=8)) -> Response:
    with connection() as conn:
        conn.execute("UPDATE push_subscriptions SET enabled = 0, updated_at = ? WHERE endpoint = ?", (utc_now(), endpoint))
        conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/push/test")
def test_push() -> dict:
    return alert_manager.test_push()


# ------------------------------- V4 rules ----------------------------------


def _rule_out(row) -> dict:
    data = dict(row)
    try:
        data["weekdays"] = json.loads(data.pop("weekdays_json"))
    except Exception:
        data["weekdays"] = list(range(7))
        data.pop("weekdays_json", None)
    return data


@router.get("/api/alert-rules")
def list_alert_rules() -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT ar.*, c.name camera_name, p.name person_name
            FROM alert_rules ar
            LEFT JOIN cameras c ON c.id = ar.camera_id
            LEFT JOIN persons p ON p.id = ar.person_id
            ORDER BY ar.enabled DESC, ar.name COLLATE NOCASE"""
        ).fetchall()
    return [_rule_out(row) for row in rows]


@router.post("/api/alert-rules", status_code=status.HTTP_201_CREATED)
def create_alert_rule(payload: AlertRuleCreate) -> dict:
    try:
        ZoneInfo(payload.timezone)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Fuso horário inválido: {payload.timezone}") from exc
    if payload.camera_id is not None:
        _camera_row(payload.camera_id)
    with connection() as conn:
        if payload.person_id is not None and conn.execute("SELECT id FROM persons WHERE id = ?", (payload.person_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Pessoa não encontrada")
        now = utc_now()
        cursor = conn.execute(
            """INSERT INTO alert_rules(
                name, enabled, camera_id, person_id, unknown_only, start_time, end_time,
                weekdays_json, timezone, cooldown_seconds, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.name, int(payload.enabled), payload.camera_id, payload.person_id,
                int(payload.unknown_only), payload.start_time, payload.end_time,
                json.dumps(payload.weekdays), payload.timezone, payload.cooldown_seconds, now, now,
            ),
        )
        rule_id = int(cursor.lastrowid)
        conn.commit()
        row = conn.execute("SELECT * FROM alert_rules WHERE id = ?", (rule_id,)).fetchone()
    return _rule_out(row)


@router.patch("/api/alert-rules/{rule_id}")
def update_alert_rule(rule_id: int, payload: AlertRuleUpdate) -> dict:
    values = payload.model_dump(exclude_unset=True)
    with connection() as conn:
        current = conn.execute("SELECT * FROM alert_rules WHERE id = ?", (rule_id,)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Regra não encontrada")
        merged = dict(current)
        merged.update(values)
        timezone_name = merged.get("timezone") or "UTC"
        try:
            ZoneInfo(timezone_name)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Fuso horário inválido: {timezone_name}") from exc
        if merged.get("unknown_only") and merged.get("person_id") is not None:
            raise HTTPException(status_code=400, detail="Escolha desconhecidos OU uma pessoa específica")
        if bool(merged.get("start_time")) != bool(merged.get("end_time")):
            raise HTTPException(status_code=400, detail="Informe horário inicial e final juntos")

        allowed = {"name", "enabled", "camera_id", "person_id", "unknown_only", "start_time", "end_time", "timezone", "cooldown_seconds"}
        assignments: list[str] = []
        params: list[object] = []
        for key, value in values.items():
            if key == "weekdays":
                assignments.append("weekdays_json = ?")
                params.append(json.dumps(value))
            elif key in allowed:
                assignments.append(f"{key} = ?")
                params.append(int(value) if key in {"enabled", "unknown_only"} and value is not None else value)
        if assignments:
            assignments.append("updated_at = ?")
            params.extend([utc_now(), rule_id])
            conn.execute(f"UPDATE alert_rules SET {', '.join(assignments)} WHERE id = ?", params)
            conn.commit()
        row = conn.execute("SELECT * FROM alert_rules WHERE id = ?", (rule_id,)).fetchone()
    return _rule_out(row)


@router.delete("/api/alert-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert_rule(rule_id: int) -> Response:
    with connection() as conn:
        conn.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
        conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------- V4 stats ----------------------------------


@router.get("/api/stats/summary")
def stats_summary(
    camera_id: int | None = None,
    person_id: int | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> dict:
    where: list[str] = ["COALESCE(e.identity_state, '') <> 'false_positive'"]
    params: list[object] = []
    if camera_id is not None:
        where.append("e.camera_id = ?")
        params.append(camera_id)
    if person_id is not None:
        where.append("e.person_id = ?")
        params.append(person_id)
    if from_ts:
        where.append("e.created_at >= ?")
        params.append(from_ts)
    if to_ts:
        where.append("e.created_at <= ?")
        params.append(to_ts)
    clause = " WHERE " + " AND ".join(where)
    with connection() as conn:
        totals = conn.execute(
            f"""SELECT COUNT(*) total,
                SUM(CASE WHEN e.person_id IS NOT NULL THEN 1 ELSE 0 END) known,
                SUM(CASE WHEN e.person_id IS NULL THEN 1 ELSE 0 END) unknown,
                SUM(CASE WHEN e.has_face = 1 THEN 1 ELSE 0 END) with_face,
                COUNT(DISTINCT e.person_id) unique_known
            FROM events e{clause}""",
            params,
        ).fetchone()
        by_camera = conn.execute(
            f"""SELECT c.id, c.name, COUNT(*) count FROM events e
            JOIN cameras c ON c.id = e.camera_id{clause}
            GROUP BY c.id, c.name ORDER BY count DESC""",
            params,
        ).fetchall()
        by_person = conn.execute(
            f"""SELECT p.id, p.name, COUNT(*) count FROM events e
            JOIN persons p ON p.id = e.person_id{clause}
            GROUP BY p.id, p.name ORDER BY count DESC LIMIT 12""",
            params,
        ).fetchall()
    return {
        "total": int(totals["total"] or 0),
        "known": int(totals["known"] or 0),
        "unknown": int(totals["unknown"] or 0),
        "with_face": int(totals["with_face"] or 0),
        "unique_known": int(totals["unique_known"] or 0),
        "by_camera": [dict(row) for row in by_camera],
        "by_person": [dict(row) for row in by_person],
    }

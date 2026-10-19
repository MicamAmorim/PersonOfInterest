from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .db import connection, utc_now


router = APIRouter(prefix="/api/push/device", tags=["push"])


@router.get("/state")
def device_push_state(endpoint: str = Query(min_length=8)) -> dict[str, Any]:
    """Return the server-side delivery state for one browser Push endpoint.

    Push subscriptions are device/browser specific. This endpoint never changes
    alert rules or any other subscription, so pausing on one phone/PC leaves all
    other enrolled devices untouched.
    """
    with connection() as conn:
        row = conn.execute(
            "SELECT id, enabled, updated_at FROM push_subscriptions WHERE endpoint = ?",
            (endpoint,),
        ).fetchone()
    if row is None:
        return {"registered": False, "enabled": False}
    return {
        "registered": True,
        "enabled": bool(row["enabled"]),
        "subscription_id": int(row["id"]),
        "updated_at": row["updated_at"],
    }


@router.patch("/state")
def set_device_push_state(payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(payload.get("endpoint") or "").strip()
    enabled = payload.get("enabled")
    if len(endpoint) < 8:
        raise HTTPException(status_code=400, detail="Endpoint Push inválido")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="enabled deve ser true ou false")

    now = utc_now()
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM push_subscriptions WHERE endpoint = ?",
            (endpoint,),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Este navegador ainda não possui uma inscrição Push registrada",
            )
        conn.execute(
            "UPDATE push_subscriptions SET enabled = ?, updated_at = ? WHERE endpoint = ?",
            (1 if enabled else 0, now, endpoint),
        )
        conn.commit()

    return {
        "ok": True,
        "registered": True,
        "enabled": enabled,
        "subscription_id": int(row["id"]),
        "updated_at": now,
    }

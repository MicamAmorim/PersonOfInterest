from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator

from .db import connection, utc_now
from .spatial_alerts import manager as spatial_alert_manager


router = APIRouter()


class NormalizedPoint(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class SpatialRulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    camera_id: int = Field(ge=1)
    kind: Literal["line_cross", "zone_dwell"]
    points: list[NormalizedPoint] = Field(min_length=2, max_length=32)
    arrow_from: NormalizedPoint | None = None
    arrow_to: NormalizedPoint | None = None
    zone_mode: Literal["inside", "outside"] | None = None
    dwell_seconds: float = Field(default=0.0, ge=0.0, le=3600.0)
    cooldown_seconds: float = Field(default=30.0, ge=0.0, le=86400.0)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_geometry(self) -> "SpatialRulePayload":
        if self.kind == "line_cross":
            if len(self.points) < 2:
                raise ValueError("A linha virtual precisa de pelo menos dois pontos")
            if self.arrow_from is None or self.arrow_to is None:
                raise ValueError("Defina a seta de direção da linha virtual")
            dx = self.arrow_to.x - self.arrow_from.x
            dy = self.arrow_to.y - self.arrow_from.y
            if dx * dx + dy * dy < 0.0001:
                raise ValueError("A seta de direção precisa ter comprimento visível")
        else:
            if len(self.points) < 3:
                raise ValueError("A cerca virtual precisa de pelo menos três pontos")
            if self.zone_mode not in {"inside", "outside"}:
                raise ValueError("Escolha se o alerta vale dentro ou fora da cerca")
        return self


class SpatialRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    camera_id: int | None = Field(default=None, ge=1)
    kind: Literal["line_cross", "zone_dwell"] | None = None
    points: list[NormalizedPoint] | None = Field(default=None, min_length=2, max_length=32)
    arrow_from: NormalizedPoint | None = None
    arrow_to: NormalizedPoint | None = None
    zone_mode: Literal["inside", "outside"] | None = None
    dwell_seconds: float | None = Field(default=None, ge=0.0, le=3600.0)
    cooldown_seconds: float | None = Field(default=None, ge=0.0, le=86400.0)


def _camera_exists(camera_id: int) -> bool:
    with connection() as conn:
        return conn.execute("SELECT id FROM cameras WHERE id = ?", (camera_id,)).fetchone() is not None


def _geometry(points: list[NormalizedPoint], arrow_from: NormalizedPoint | None, arrow_to: NormalizedPoint | None) -> str:
    data: dict = {
        "points": [point.model_dump() for point in points],
    }
    if arrow_from is not None and arrow_to is not None:
        data["arrow"] = {"from": arrow_from.model_dump(), "to": arrow_to.model_dump()}
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _row_out(row) -> dict:
    data = dict(row)
    try:
        geometry = json.loads(data.pop("geometry_json") or "{}")
    except Exception:
        geometry = {}
    data["points"] = geometry.get("points") or []
    arrow = geometry.get("arrow") or {}
    data["arrow_from"] = arrow.get("from")
    data["arrow_to"] = arrow.get("to")
    data["enabled"] = bool(data.get("enabled"))
    return data


def _load_rule(rule_id: int):
    spatial_alert_manager.ensure_schema()
    with connection() as conn:
        return conn.execute(
            """SELECT sar.*, c.name camera_name
            FROM spatial_alert_rules sar
            JOIN cameras c ON c.id = sar.camera_id
            WHERE sar.id = ?""",
            (rule_id,),
        ).fetchone()


@router.get("/api/spatial-alerts/status")
def spatial_alert_status() -> dict:
    return spatial_alert_manager.state()


@router.get("/api/spatial-alerts/rules")
def list_spatial_rules() -> list[dict]:
    spatial_alert_manager.ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT sar.*, c.name camera_name
            FROM spatial_alert_rules sar
            JOIN cameras c ON c.id = sar.camera_id
            ORDER BY sar.enabled DESC, sar.name COLLATE NOCASE"""
        ).fetchall()
    return [_row_out(row) for row in rows]


@router.post("/api/spatial-alerts/rules", status_code=status.HTTP_201_CREATED)
def create_spatial_rule(payload: SpatialRulePayload) -> dict:
    spatial_alert_manager.ensure_schema()
    if not _camera_exists(payload.camera_id):
        raise HTTPException(status_code=404, detail="Câmera não encontrada")
    geometry_json = _geometry(payload.points, payload.arrow_from, payload.arrow_to)
    now = utc_now()
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO spatial_alert_rules(
                name, enabled, camera_id, kind, geometry_json, zone_mode,
                dwell_seconds, cooldown_seconds, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.name.strip(), int(payload.enabled), payload.camera_id, payload.kind,
                geometry_json, payload.zone_mode if payload.kind == "zone_dwell" else None,
                payload.dwell_seconds if payload.kind == "zone_dwell" else 0.0,
                payload.cooldown_seconds, now, now,
            ),
        )
        rule_id = int(cursor.lastrowid)
        conn.commit()
    spatial_alert_manager.notify_change(payload.camera_id)
    row = _load_rule(rule_id)
    return _row_out(row)


@router.patch("/api/spatial-alerts/rules/{rule_id}")
def update_spatial_rule(rule_id: int, payload: SpatialRuleUpdate) -> dict:
    current = _load_rule(rule_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Regra espacial não encontrada")
    current_data = _row_out(current)
    incoming = payload.model_dump(exclude_unset=True)
    merged = dict(current_data)
    merged.update(incoming)
    camera_id = int(merged["camera_id"])
    if not _camera_exists(camera_id):
        raise HTTPException(status_code=404, detail="Câmera não encontrada")

    try:
        validated = SpatialRulePayload(
            name=str(merged["name"]),
            enabled=bool(merged["enabled"]),
            camera_id=camera_id,
            kind=str(merged["kind"]),
            points=merged.get("points") or [],
            arrow_from=merged.get("arrow_from"),
            arrow_to=merged.get("arrow_to"),
            zone_mode=merged.get("zone_mode"),
            dwell_seconds=float(merged.get("dwell_seconds") or 0.0),
            cooldown_seconds=float(merged.get("cooldown_seconds") or 0.0),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    geometry_json = _geometry(validated.points, validated.arrow_from, validated.arrow_to)
    with connection() as conn:
        conn.execute(
            """UPDATE spatial_alert_rules SET
                name = ?, enabled = ?, camera_id = ?, kind = ?, geometry_json = ?,
                zone_mode = ?, dwell_seconds = ?, cooldown_seconds = ?, updated_at = ?
            WHERE id = ?""",
            (
                validated.name.strip(), int(validated.enabled), validated.camera_id,
                validated.kind, geometry_json,
                validated.zone_mode if validated.kind == "zone_dwell" else None,
                validated.dwell_seconds if validated.kind == "zone_dwell" else 0.0,
                validated.cooldown_seconds, utc_now(), rule_id,
            ),
        )
        conn.commit()
    spatial_alert_manager.notify_change()
    return _row_out(_load_rule(rule_id))


@router.delete("/api/spatial-alerts/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_spatial_rule(rule_id: int) -> Response:
    spatial_alert_manager.ensure_schema()
    with connection() as conn:
        row = conn.execute("SELECT camera_id FROM spatial_alert_rules WHERE id = ?", (rule_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Regra espacial não encontrada")
        camera_id = int(row["camera_id"])
        conn.execute("DELETE FROM spatial_alert_rules WHERE id = ?", (rule_id,))
        conn.commit()
    spatial_alert_manager.notify_change(camera_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/spatial-alerts/events")
def list_spatial_events(limit: int = 30) -> list[dict]:
    spatial_alert_manager.ensure_schema()
    limit = max(1, min(100, int(limit)))
    with connection() as conn:
        rows = conn.execute(
            """SELECT sae.*, sar.name rule_name, c.name camera_name
            FROM spatial_alert_events sae
            JOIN spatial_alert_rules sar ON sar.id = sae.rule_id
            JOIN cameras c ON c.id = sae.camera_id
            ORDER BY sae.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]

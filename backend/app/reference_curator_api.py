from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import body_identity as bi
from . import identity as fi
from .config import DATA_DIR, EVENTS_DIR, FACES_DIR
from .db import connection, utc_now
from .reference_curator_patch import ensure_curator_schema
from .tracking_v5_patch import BODY_ANCHORS_DIR


router = APIRouter(tags=["v5-reference-curation"])


class ReferenceStateRequest(BaseModel):
    active: bool | None = None
    trusted: bool | None = None


class MoveReferenceRequest(BaseModel):
    target_person_id: int = Field(gt=0)
    sync_event: bool = False


def _person(person_id: int) -> dict[str, Any]:
    ensure_curator_schema()
    with connection() as conn:
        row = conn.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    return dict(row)


def _safe_under(root: Path, relative: str | None) -> Path | None:
    if not relative:
        return None
    path = (root / relative).resolve()
    resolved = root.resolve()
    if resolved not in path.parents or not path.is_file():
        return None
    return path


def _copy_face_crop(relative: str | None, target_person_id: int) -> str | None:
    source = _safe_under(FACES_DIR, relative)
    if source is None:
        return None
    folder = FACES_DIR / "anchors" / str(target_person_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("+", "_").replace(".", "_")
    target = folder / f"reassigned_{stamp}{source.suffix or '.jpg'}"
    shutil.copy2(source, target)
    return str(target.relative_to(FACES_DIR)).replace("\\", "/")


def _body_crop_from_event(event_id: int, target_person_id: int) -> str | None:
    if fi.cv2 is None:
        return None
    with connection() as conn:
        row = conn.execute(
            "SELECT snapshot_path, bbox_json FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
    if row is None:
        return None
    path = _safe_under(EVENTS_DIR, row["snapshot_path"])
    if path is None:
        return None
    frame = fi.cv2.imread(str(path))
    if frame is None:
        return None
    try:
        bbox = json.loads(row["bbox_json"] or "{}")
        x = int(float(bbox.get("x", 0)))
        y = int(float(bbox.get("y", 0)))
        w = int(float(bbox.get("w", 0)))
        h = int(float(bbox.get("h", 0)))
    except Exception:
        return None
    height, width = frame.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(width, x + w), min(height, y + h)
    if x2 - x1 < 18 or y2 - y1 < 36:
        return None
    crop = frame[y1:y2, x1:x2]
    folder = BODY_ANCHORS_DIR / str(target_person_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("+", "_").replace(".", "_")
    target = folder / f"reassigned_{stamp}.jpg"
    if not fi.cv2.imwrite(str(target), crop, [int(fi.cv2.IMWRITE_JPEG_QUALITY), 92]):
        return None
    return str(target.relative_to(DATA_DIR)).replace("\\", "/")


def _state_name(*, active: bool, trusted: bool, kind: str) -> str:
    if not active:
        return "disabled"
    if kind == "body" and not trusted:
        return "quarantine"
    return "trusted"


@router.get("/api/v5/curation/persons")
def curated_persons() -> list[dict[str, Any]]:
    ensure_curator_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT p.id, p.name, p.created_at, p.updated_at,
                (SELECT COUNT(*) FROM events e WHERE e.person_id = p.id) event_count,
                (SELECT COUNT(*) FROM face_samples fs
                    WHERE fs.person_id = p.id AND fs.active = 1 AND fs.user_disabled = 0) +
                (SELECT COUNT(*) FROM person_face_anchors fa
                    WHERE fa.person_id = p.id AND fa.active = 1) face_reference_count,
                (SELECT COUNT(*) FROM body_samples bs
                    WHERE bs.person_id = p.id AND bs.active = 1 AND bs.user_disabled = 0 AND bs.trusted = 1) +
                (SELECT COUNT(*) FROM person_body_anchors ba
                    WHERE ba.person_id = p.id AND ba.active = 1) trusted_body_reference_count,
                (SELECT COUNT(*) FROM body_samples bs
                    WHERE bs.person_id = p.id AND bs.active = 1 AND bs.user_disabled = 0 AND bs.trusted = 0) quarantined_body_count,
                (SELECT COUNT(*) FROM face_samples fs
                    WHERE fs.person_id = p.id AND (fs.active = 0 OR fs.user_disabled = 1)) +
                (SELECT COUNT(*) FROM person_face_anchors fa
                    WHERE fa.person_id = p.id AND fa.active = 0) +
                (SELECT COUNT(*) FROM body_samples bs
                    WHERE bs.person_id = p.id AND (bs.active = 0 OR bs.user_disabled = 1)) +
                (SELECT COUNT(*) FROM person_body_anchors ba
                    WHERE ba.person_id = p.id AND ba.active = 0) disabled_reference_count
            FROM persons p ORDER BY p.name COLLATE NOCASE"""
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/api/v5/curation/persons/{person_id}/references")
def curated_references(person_id: int) -> dict[str, Any]:
    person = _person(person_id)
    with connection() as conn:
        face_anchors = conn.execute(
            """SELECT id, quality, source, active, created_at
            FROM person_face_anchors WHERE person_id = ? ORDER BY active DESC, created_at DESC""",
            (person_id,),
        ).fetchall()
        face_events = conn.execute(
            """SELECT fs.id, fs.event_id, fs.quality, fs.active, fs.user_disabled,
                fs.created_at, COALESCE(e.identity_origin, 'event') source
            FROM face_samples fs LEFT JOIN events e ON e.id = fs.event_id
            WHERE fs.person_id = ? ORDER BY fs.active DESC, fs.created_at DESC""",
            (person_id,),
        ).fetchall()
        body_anchors = conn.execute(
            """SELECT id, quality, source, active, created_at
            FROM person_body_anchors WHERE person_id = ? ORDER BY active DESC, created_at DESC""",
            (person_id,),
        ).fetchall()
        body_events = conn.execute(
            """SELECT id, event_id, quality, source, trusted, active, user_disabled,
                temporal_support, stability, created_at
            FROM body_samples WHERE person_id = ?
            ORDER BY active DESC, trusted DESC, quality DESC, created_at DESC""",
            (person_id,),
        ).fetchall()

    references: list[dict[str, Any]] = []
    for row in face_anchors:
        item = dict(row)
        active = bool(item["active"])
        references.append({
            **item,
            "type": "face",
            "trusted": True,
            "active": active,
            "state": _state_name(active=active, trusted=True, kind="face"),
            "ref_kind": "face-anchor",
            "image_url": f"/api/v5/face-anchors/{item['id']}/image",
        })
    for row in face_events:
        item = dict(row)
        active = bool(item["active"]) and not bool(item["user_disabled"])
        references.append({
            **item,
            "type": "face",
            "trusted": True,
            "active": active,
            "state": _state_name(active=active, trusted=True, kind="face"),
            "ref_kind": "face-event",
            "image_url": f"/api/v5/face-samples/{item['id']}/image",
        })
    for row in body_anchors:
        item = dict(row)
        active = bool(item["active"])
        references.append({
            **item,
            "type": "body",
            "trusted": True,
            "active": active,
            "state": _state_name(active=active, trusted=True, kind="body"),
            "ref_kind": "body-anchor",
            "image_url": f"/api/v5/body-anchors/{item['id']}/image",
        })
    for row in body_events:
        item = dict(row)
        active = bool(item["active"]) and not bool(item["user_disabled"])
        trusted = bool(item["trusted"])
        references.append({
            **item,
            "type": "body",
            "trusted": trusted,
            "active": active,
            "state": _state_name(active=active, trusted=trusted, kind="body"),
            "ref_kind": "body-event",
            "image_url": f"/api/events/{item['event_id']}/snapshot",
        })

    groups = {
        "trusted": [item for item in references if item["state"] == "trusted"],
        "quarantine": [item for item in references if item["state"] == "quarantine"],
        "disabled": [item for item in references if item["state"] == "disabled"],
    }
    return {"person": person, "groups": groups, "references": references}


@router.patch("/api/v5/curation/persons/{person_id}/references/{ref_kind}/{reference_id}/state")
def update_reference_state(
    person_id: int,
    ref_kind: str,
    reference_id: int,
    payload: ReferenceStateRequest,
) -> dict[str, Any]:
    _person(person_id)
    ensure_curator_schema()
    if payload.active is None and payload.trusted is None:
        raise HTTPException(status_code=400, detail="Informe active ou trusted")

    with connection() as conn:
        if ref_kind == "face-anchor":
            row = conn.execute(
                "SELECT id FROM person_face_anchors WHERE id = ? AND person_id = ?",
                (reference_id, person_id),
            ).fetchone()
            if row and payload.active is not None:
                conn.execute("UPDATE person_face_anchors SET active = ? WHERE id = ?", (int(payload.active), reference_id))
        elif ref_kind == "face-event":
            row = conn.execute(
                "SELECT id FROM face_samples WHERE id = ? AND person_id = ?",
                (reference_id, person_id),
            ).fetchone()
            if row and payload.active is not None:
                conn.execute(
                    "UPDATE face_samples SET active = ?, user_disabled = ? WHERE id = ?",
                    (int(payload.active), int(not payload.active), reference_id),
                )
        elif ref_kind == "body-anchor":
            row = conn.execute(
                "SELECT id FROM person_body_anchors WHERE id = ? AND person_id = ?",
                (reference_id, person_id),
            ).fetchone()
            if row and payload.active is not None:
                conn.execute("UPDATE person_body_anchors SET active = ? WHERE id = ?", (int(payload.active), reference_id))
        elif ref_kind == "body-event":
            row = conn.execute(
                "SELECT id, trusted FROM body_samples WHERE id = ? AND person_id = ?",
                (reference_id, person_id),
            ).fetchone()
            if row and payload.active is not None:
                conn.execute(
                    "UPDATE body_samples SET active = ?, user_disabled = ? WHERE id = ?",
                    (int(payload.active), int(not payload.active), reference_id),
                )
            if row and payload.trusted is True:
                conn.execute(
                    """UPDATE body_samples SET trusted = 1, verified = 1, active = 1,
                        user_disabled = 0, source = 'manual_validated', updated_at = ?
                    WHERE id = ?""",
                    (utc_now(), reference_id),
                )
            elif row and payload.trusted is False:
                raise HTTPException(
                    status_code=400,
                    detail="Para retirar uma âncora confiável, desative-a ou exclua-a. Quarentena manual reversa não é permitida.",
                )
        else:
            raise HTTPException(status_code=400, detail="Tipo de referência inválido")
        if row is None:
            raise HTTPException(status_code=404, detail="Referência não encontrada")
        conn.commit()

    bi.manager.notify_change()
    return {"ok": True, "person_id": person_id, "ref_kind": ref_kind, "reference_id": reference_id}


@router.post("/api/v5/curation/persons/{person_id}/references/{ref_kind}/{reference_id}/move")
def move_reference(
    person_id: int,
    ref_kind: str,
    reference_id: int,
    payload: MoveReferenceRequest,
) -> dict[str, Any]:
    source_person = _person(person_id)
    target_person = _person(payload.target_person_id)
    if int(person_id) == int(payload.target_person_id):
        raise HTTPException(status_code=400, detail="A referência já pertence a essa pessoa")
    ensure_curator_schema()

    created_ref_kind = ref_kind
    created_reference_id = reference_id
    event_id: int | None = None

    if ref_kind == "face-anchor":
        with connection() as conn:
            row = conn.execute(
                "SELECT id FROM person_face_anchors WHERE id = ? AND person_id = ?",
                (reference_id, person_id),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Referência não encontrada")
            conn.execute(
                "UPDATE person_face_anchors SET person_id = ?, active = 1, source = 'manual_reassigned' WHERE id = ?",
                (payload.target_person_id, reference_id),
            )
            conn.commit()

    elif ref_kind == "body-anchor":
        with connection() as conn:
            row = conn.execute(
                "SELECT id FROM person_body_anchors WHERE id = ? AND person_id = ?",
                (reference_id, person_id),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Referência não encontrada")
            conn.execute(
                "UPDATE person_body_anchors SET person_id = ?, active = 1, source = 'manual_reassigned' WHERE id = ?",
                (payload.target_person_id, reference_id),
            )
            conn.commit()

    elif ref_kind == "face-event":
        with connection() as conn:
            row = conn.execute(
                """SELECT id, event_id, embedding, crop_path, quality
                FROM face_samples WHERE id = ? AND person_id = ?""",
                (reference_id, person_id),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Referência não encontrada")
        event_id = int(row["event_id"])
        if payload.sync_event:
            fi.manager.assign_event(event_id, person_id=payload.target_person_id)
            with connection() as conn:
                conn.execute(
                    """UPDATE face_samples SET person_id = ?, active = 1, user_disabled = 0
                    WHERE id = ?""",
                    (payload.target_person_id, reference_id),
                )
                conn.commit()
        else:
            copied = _copy_face_crop(row["crop_path"], payload.target_person_id)
            with connection() as conn:
                cursor = conn.execute(
                    """INSERT INTO person_face_anchors(person_id, embedding, crop_path, quality, source, active, created_at)
                    VALUES (?, ?, ?, ?, 'manual_reassigned', 1, ?)""",
                    (
                        payload.target_person_id, row["embedding"], copied,
                        float(row["quality"] or 0.0), utc_now(),
                    ),
                )
                conn.execute(
                    "UPDATE face_samples SET active = 0, user_disabled = 1 WHERE id = ?",
                    (reference_id,),
                )
                conn.commit()
                created_reference_id = int(cursor.lastrowid)
                created_ref_kind = "face-anchor"

    elif ref_kind == "body-event":
        with connection() as conn:
            row = conn.execute(
                """SELECT id, event_id, embedding, quality
                FROM body_samples WHERE id = ? AND person_id = ?""",
                (reference_id, person_id),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Referência não encontrada")
        event_id = int(row["event_id"])
        if payload.sync_event:
            fi.manager.assign_event(event_id, person_id=payload.target_person_id)
            bi.manager.confirm_event_identity(event_id, payload.target_person_id)
            with connection() as conn:
                conn.execute(
                    """UPDATE body_samples SET person_id = ?, verified = 1, trusted = 1,
                        active = 1, user_disabled = 0, source = 'manual_reassigned_event', updated_at = ?
                    WHERE id = ?""",
                    (payload.target_person_id, utc_now(), reference_id),
                )
                conn.commit()
        else:
            copied = _body_crop_from_event(event_id, payload.target_person_id)
            with connection() as conn:
                cursor = conn.execute(
                    """INSERT INTO person_body_anchors(person_id, embedding, crop_path, quality, source, active, created_at)
                    VALUES (?, ?, ?, ?, 'manual_reassigned', 1, ?)""",
                    (
                        payload.target_person_id, row["embedding"], copied,
                        float(row["quality"] or 0.0), utc_now(),
                    ),
                )
                conn.execute(
                    "UPDATE body_samples SET active = 0, user_disabled = 1 WHERE id = ?",
                    (reference_id,),
                )
                conn.commit()
                created_reference_id = int(cursor.lastrowid)
                created_ref_kind = "body-anchor"
    else:
        raise HTTPException(status_code=400, detail="Tipo de referência inválido")

    bi.manager.notify_change()
    return {
        "ok": True,
        "from_person": {"id": int(source_person["id"]), "name": source_person["name"]},
        "to_person": {"id": int(target_person["id"]), "name": target_person["name"]},
        "sync_event": bool(payload.sync_event),
        "event_id": event_id,
        "reference": {"kind": created_ref_kind, "id": created_reference_id},
    }

from __future__ import annotations

import base64
import binascii
import math
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import body_identity as bi
from . import identity as fi
from . import vision
from .config import DATA_DIR, FACES_DIR
from .db import connection, utc_now
from .tracking_v5_patch import BODY_ANCHORS_DIR, ensure_schema


router = APIRouter(tags=["v5-persistent-identity"])


class ImportReferenceRequest(BaseModel):
    image_base64: str = Field(min_length=8)
    kind: str = "face"
    filename: str | None = None


def _person(person_id: int) -> dict[str, Any]:
    ensure_schema()
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


def _unlink(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _decode_image(raw: str) -> Any:
    if fi.cv2 is None or fi.np is None:
        raise HTTPException(status_code=503, detail="OpenCV indisponível")
    if "," in raw and raw.lstrip().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        payload = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Imagem base64 inválida") from exc
    if len(payload) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Imagem maior que 10 MB")
    data = fi.np.frombuffer(payload, dtype=fi.np.uint8)
    frame = fi.cv2.imdecode(data, fi.cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Não foi possível decodificar a imagem")
    return frame


def _fresh_face_models() -> tuple[Any, Any]:
    if not fi.CV_AVAILABLE:
        raise HTTPException(status_code=503, detail=fi.CV_ERROR or "OpenCV indisponível")
    if not fi.FACE_DETECTOR_MODEL_PATH.is_file() or not fi.FACE_RECOGNIZER_MODEL_PATH.is_file():
        raise HTTPException(status_code=503, detail="Modelos YuNet/SFace indisponíveis")
    create_detector = getattr(fi.cv2, "FaceDetectorYN_create", None)
    detector = (
        create_detector(
            str(fi.FACE_DETECTOR_MODEL_PATH), "", (320, 320),
            fi.IDENTITY_FACE_SCORE_THRESHOLD, 0.30, 5000,
        )
        if create_detector
        else fi.cv2.FaceDetectorYN.create(
            str(fi.FACE_DETECTOR_MODEL_PATH), "", (320, 320),
            fi.IDENTITY_FACE_SCORE_THRESHOLD, 0.30, 5000,
        )
    )
    create_recognizer = getattr(fi.cv2, "FaceRecognizerSF_create", None)
    recognizer = (
        create_recognizer(str(fi.FACE_RECOGNIZER_MODEL_PATH), "")
        if create_recognizer
        else fi.cv2.FaceRecognizerSF.create(str(fi.FACE_RECOGNIZER_MODEL_PATH), "")
    )
    return detector, recognizer


def _face_reference(frame: Any, person_id: int, source: str, bbox: dict[str, int] | None = None) -> dict[str, Any]:
    detector, recognizer = _fresh_face_models()
    height, width = frame.shape[:2]
    detector.setInputSize((width, height))
    _, faces = detector.detect(frame)
    if faces is None or len(faces) == 0:
        raise HTTPException(status_code=422, detail="Nenhum rosto útil encontrado na imagem")
    candidates = list(faces)
    if bbox:
        x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
        candidates = [
            face for face in faces
            if x <= float(face[0] + face[2] / 2) <= x + w
            and y <= float(face[1] + face[3] / 2) <= y + h
        ]
        if not candidates:
            raise HTTPException(status_code=422, detail="Nenhum rosto foi encontrado dentro do track selecionado")
    face = max(candidates, key=lambda value: float(value[-1]) * max(1.0, float(value[2] * value[3])))
    aligned = recognizer.alignCrop(frame, face)
    embedding = fi._normalize(recognizer.feature(aligned))
    score = float(face[-1])
    fw, fh = max(1.0, float(face[2])), max(1.0, float(face[3]))
    quality = max(0.0, min(1.0, score * min(1.0, math.sqrt(fw * fh) / 110.0)))
    folder = FACES_DIR / "anchors" / str(person_id)
    folder.mkdir(parents=True, exist_ok=True)
    now_key = utc_now().replace(":", "").replace("+", "_").replace(".", "_")
    path = folder / f"face_{now_key}.jpg"
    if not fi.cv2.imwrite(str(path), aligned, [int(fi.cv2.IMWRITE_JPEG_QUALITY), 94]):
        raise HTTPException(status_code=500, detail="Falha ao salvar referência facial")
    relative = str(path.relative_to(FACES_DIR)).replace("\\", "/")
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO person_face_anchors(person_id, embedding, crop_path, quality, source, active, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (person_id, fi._vector_to_blob(embedding), relative, quality, source, utc_now()),
        )
        conn.commit()
        anchor_id = int(cursor.lastrowid)
    return {"id": anchor_id, "kind": "face", "quality": quality, "source": source}


def _body_reference(frame: Any, person_id: int, source: str, bbox: dict[str, int] | None = None, confidence: float = 0.9) -> dict[str, Any]:
    if not bi.manager.available:
        raise HTTPException(status_code=503, detail=bi.manager.error or "Body ReID indisponível")
    height, width = frame.shape[:2]
    if bbox:
        x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(width, x + w), min(height, y + h)
        crop = frame[y1:y2, x1:x2]
        touches = x1 <= 1 or y1 <= 1 or x2 >= width - 1 or y2 >= height - 1
        area_ratio = (max(1, x2 - x1) * max(1, y2 - y1)) / max(1.0, float(width * height))
        size_quality = min(1.0, math.sqrt(area_ratio / 0.16))
        quality = max(0.20, min(1.0, (0.55 * confidence + 0.45 * size_quality) * (0.72 if touches else 1.0)))
    else:
        crop = frame
        # Imported body references are user-confirmed, but an uncropped image can
        # contain background; keep a conservative quality so several anchors win.
        quality = 0.70
    if crop is None or crop.size == 0 or crop.shape[0] < 48 or crop.shape[1] < 24:
        raise HTTPException(status_code=422, detail="Recorte corporal pequeno demais")
    try:
        embedding = bi.manager._embed_crop(crop)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Falha no Body ReID: {exc}") from exc
    folder = BODY_ANCHORS_DIR / str(person_id)
    folder.mkdir(parents=True, exist_ok=True)
    now_key = utc_now().replace(":", "").replace("+", "_").replace(".", "_")
    path = folder / f"body_{now_key}.jpg"
    if not fi.cv2.imwrite(str(path), crop, [int(fi.cv2.IMWRITE_JPEG_QUALITY), 92]):
        raise HTTPException(status_code=500, detail="Falha ao salvar referência corporal")
    relative = str(path.relative_to(DATA_DIR)).replace("\\", "/")
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO person_body_anchors(person_id, embedding, crop_path, quality, source, active, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (person_id, bi._vector_to_blob(embedding), relative, quality, source, utc_now()),
        )
        conn.commit()
        anchor_id = int(cursor.lastrowid)
    bi.manager.notify_change()
    return {"id": anchor_id, "kind": "body", "quality": quality, "source": source}


def _enroll(frame: Any, person_id: int, kind: str, source: str, bbox: dict[str, int] | None = None, confidence: float = 0.9) -> dict[str, Any]:
    kind = kind.strip().lower()
    if kind not in {"face", "body", "both"}:
        raise HTTPException(status_code=400, detail="kind deve ser face, body ou both")
    created: list[dict[str, Any]] = []
    errors: list[str] = []
    if kind in {"face", "both"}:
        try:
            created.append(_face_reference(frame, person_id, source, bbox))
        except HTTPException as exc:
            if kind == "face":
                raise
            errors.append(str(exc.detail))
    if kind in {"body", "both"}:
        try:
            created.append(_body_reference(frame, person_id, source, bbox, confidence))
        except HTTPException as exc:
            if kind == "body":
                raise
            errors.append(str(exc.detail))
    if not created:
        raise HTTPException(status_code=422, detail="; ".join(errors) or "Nenhuma referência pôde ser criada")
    return {"ok": True, "person_id": person_id, "created": created, "warnings": errors}


@router.get("/api/v5/persons")
def persons_v5() -> list[dict[str, Any]]:
    ensure_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT p.id, p.name, p.created_at, p.updated_at,
                (SELECT COUNT(*) FROM events e WHERE e.person_id = p.id) event_count,
                (SELECT COUNT(*) FROM face_samples fs WHERE fs.person_id = p.id) +
                    (SELECT COUNT(*) FROM person_face_anchors fa WHERE fa.person_id = p.id AND fa.active = 1) face_reference_count,
                (SELECT COUNT(*) FROM body_samples bs WHERE bs.person_id = p.id AND bs.active = 1 AND bs.trusted = 1) +
                    (SELECT COUNT(*) FROM person_body_anchors ba WHERE ba.person_id = p.id AND ba.active = 1) trusted_body_reference_count,
                (SELECT COUNT(*) FROM body_samples bs WHERE bs.person_id = p.id AND bs.active = 1 AND bs.trusted = 0) quarantined_body_count
            FROM persons p ORDER BY p.name COLLATE NOCASE"""
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/api/v5/persons/{person_id}/references")
def person_references(person_id: int) -> dict[str, Any]:
    person = _person(person_id)
    with connection() as conn:
        face_anchors = conn.execute(
            "SELECT id, quality, source, created_at FROM person_face_anchors WHERE person_id = ? AND active = 1 ORDER BY created_at DESC",
            (person_id,),
        ).fetchall()
        face_events = conn.execute(
            """SELECT fs.id, fs.event_id, fs.quality, fs.created_at, e.identity_origin source
            FROM face_samples fs LEFT JOIN events e ON e.id = fs.event_id
            WHERE fs.person_id = ? ORDER BY fs.created_at DESC""",
            (person_id,),
        ).fetchall()
        body_anchors = conn.execute(
            "SELECT id, quality, source, created_at FROM person_body_anchors WHERE person_id = ? AND active = 1 ORDER BY created_at DESC",
            (person_id,),
        ).fetchall()
        body_events = conn.execute(
            """SELECT id, event_id, quality, source, trusted, active, temporal_support, stability, created_at
            FROM body_samples WHERE person_id = ? ORDER BY trusted DESC, quality DESC, created_at DESC""",
            (person_id,),
        ).fetchall()
    return {
        "person": person,
        "face": [
            {**dict(row), "ref_kind": "face-anchor", "image_url": f"/api/v5/face-anchors/{row['id']}/image"}
            for row in face_anchors
        ] + [
            {**dict(row), "ref_kind": "face-event", "image_url": f"/api/v5/face-samples/{row['id']}/image"}
            for row in face_events
        ],
        "body": [
            {**dict(row), "trusted": True, "ref_kind": "body-anchor", "image_url": f"/api/v5/body-anchors/{row['id']}/image"}
            for row in body_anchors
        ] + [
            {**dict(row), "trusted": bool(row["trusted"]), "active": bool(row["active"]), "ref_kind": "body-event", "image_url": f"/api/events/{row['event_id']}/snapshot"}
            for row in body_events
        ],
    }


@router.post("/api/v5/persons/{person_id}/enroll/import", status_code=status.HTTP_201_CREATED)
def enroll_import(person_id: int, payload: ImportReferenceRequest) -> dict[str, Any]:
    _person(person_id)
    frame = _decode_image(payload.image_base64)
    return _enroll(frame, person_id, payload.kind, "manual_import")


@router.post("/api/v5/persons/{person_id}/enroll/camera/{camera_id}", status_code=status.HTTP_201_CREATED)
def enroll_camera(
    person_id: int,
    camera_id: int,
    track_id: int | None = Query(default=None, ge=1),
    kind: str = Query(default="both"),
) -> dict[str, Any]:
    _person(person_id)
    scene = vision.manager.live_scene(camera_id)
    tracks = list(scene.get("tracks") or [])
    if track_id is not None:
        tracks = [item for item in tracks if int(item["track_id"]) == track_id]
        if not tracks:
            raise HTTPException(status_code=404, detail="Track ativo não encontrado")
    elif len(tracks) > 1:
        raise HTTPException(
            status_code=409,
            detail={"message": "Há mais de uma pessoa na câmera; escolha o track_id", "tracks": tracks},
        )
    elif not tracks:
        raise HTTPException(status_code=409, detail="Nenhuma pessoa ativa diante da câmera")
    frame, at = vision.manager.latest_frame(camera_id)
    if frame is None or time.monotonic() - at > 2.0:
        raise HTTPException(status_code=409, detail="Frame ao vivo indisponível ou antigo")
    selected = tracks[0]
    bbox = {key: int(selected["bbox"][key]) for key in ("x", "y", "w", "h")}
    return _enroll(frame, person_id, kind, "manual_camera", bbox, float(selected.get("confidence") or 0.9))


@router.delete("/api/v5/persons/{person_id}/references/{ref_kind}/{reference_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reference(person_id: int, ref_kind: str, reference_id: int) -> Response:
    _person(person_id)
    ensure_schema()
    path: Path | None = None
    row = None
    with connection() as conn:
        if ref_kind == "face-anchor":
            row = conn.execute("SELECT crop_path FROM person_face_anchors WHERE id = ? AND person_id = ?", (reference_id, person_id)).fetchone()
            if row:
                path = _safe_under(FACES_DIR, row["crop_path"])
                conn.execute("DELETE FROM person_face_anchors WHERE id = ?", (reference_id,))
        elif ref_kind == "face-event":
            row = conn.execute("SELECT crop_path FROM face_samples WHERE id = ? AND person_id = ?", (reference_id, person_id)).fetchone()
            if row:
                path = _safe_under(FACES_DIR, row["crop_path"])
                conn.execute("DELETE FROM face_samples WHERE id = ?", (reference_id,))
        elif ref_kind == "body-anchor":
            row = conn.execute("SELECT crop_path FROM person_body_anchors WHERE id = ? AND person_id = ?", (reference_id, person_id)).fetchone()
            if row:
                path = _safe_under(DATA_DIR, row["crop_path"])
                conn.execute("DELETE FROM person_body_anchors WHERE id = ?", (reference_id,))
        elif ref_kind == "body-event":
            row = conn.execute("SELECT id FROM body_samples WHERE id = ? AND person_id = ?", (reference_id, person_id)).fetchone()
            if row:
                conn.execute("DELETE FROM body_samples WHERE id = ?", (reference_id,))
        else:
            raise HTTPException(status_code=400, detail="Tipo de referência inválido")
        if row is None:
            raise HTTPException(status_code=404, detail="Referência não encontrada")
        conn.commit()
    _unlink(path)
    bi.manager.notify_change()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _clear_person_references(person_id: int) -> int:
    ensure_schema()
    files: list[Path] = []
    with connection() as conn:
        for row in conn.execute("SELECT crop_path FROM person_face_anchors WHERE person_id = ?", (person_id,)).fetchall():
            path = _safe_under(FACES_DIR, row["crop_path"])
            if path:
                files.append(path)
        for row in conn.execute("SELECT crop_path FROM face_samples WHERE person_id = ?", (person_id,)).fetchall():
            path = _safe_under(FACES_DIR, row["crop_path"])
            if path:
                files.append(path)
        for row in conn.execute("SELECT crop_path FROM person_body_anchors WHERE person_id = ?", (person_id,)).fetchall():
            path = _safe_under(DATA_DIR, row["crop_path"])
            if path:
                files.append(path)
        counts = [
            int(conn.execute("SELECT COUNT(*) FROM person_face_anchors WHERE person_id = ?", (person_id,)).fetchone()[0]),
            int(conn.execute("SELECT COUNT(*) FROM face_samples WHERE person_id = ?", (person_id,)).fetchone()[0]),
            int(conn.execute("SELECT COUNT(*) FROM person_body_anchors WHERE person_id = ?", (person_id,)).fetchone()[0]),
            int(conn.execute("SELECT COUNT(*) FROM body_samples WHERE person_id = ?", (person_id,)).fetchone()[0]),
        ]
        conn.execute("DELETE FROM person_face_anchors WHERE person_id = ?", (person_id,))
        conn.execute("DELETE FROM person_body_anchors WHERE person_id = ?", (person_id,))
        conn.execute("DELETE FROM face_samples WHERE person_id = ?", (person_id,))
        conn.execute("DELETE FROM body_samples WHERE person_id = ?", (person_id,))
        conn.commit()
    for path in files:
        _unlink(path)
    bi.manager.notify_change()
    return sum(counts)


@router.delete("/api/v5/persons/{person_id}/references")
def clear_person_references(person_id: int) -> dict[str, Any]:
    _person(person_id)
    deleted = _clear_person_references(person_id)
    return {"ok": True, "person_id": person_id, "deleted": deleted}


@router.delete("/api/v5/persons/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_person_v5(person_id: int) -> Response:
    _person(person_id)
    ensure_schema()
    _clear_person_references(person_id)
    with connection() as conn:
        event_ids = [
            int(row["id"]) for row in conn.execute(
                "SELECT id FROM events WHERE person_id = ? OR probable_person_id = ?", (person_id, person_id)
            ).fetchall()
        ]
        if event_ids:
            marks = ",".join("?" for _ in event_ids)
            conn.execute(
                f"""UPDATE events SET person_id = NULL, probable_person_id = NULL, body_confidence = NULL,
                    body_identity_source = NULL, identity_state = 'pending', identity_confidence = NULL,
                    identity_origin = 'vision', assistant_eligible = 0 WHERE id IN ({marks})""",
                event_ids,
            )
        conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))
        conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/v5/face-anchors/{anchor_id}/image")
def face_anchor_image(anchor_id: int) -> FileResponse:
    ensure_schema()
    with connection() as conn:
        row = conn.execute("SELECT crop_path FROM person_face_anchors WHERE id = ?", (anchor_id,)).fetchone()
    path = _safe_under(FACES_DIR, row["crop_path"] if row else None)
    if path is None:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.get("/api/v5/body-anchors/{anchor_id}/image")
def body_anchor_image(anchor_id: int) -> FileResponse:
    ensure_schema()
    with connection() as conn:
        row = conn.execute("SELECT crop_path FROM person_body_anchors WHERE id = ?", (anchor_id,)).fetchone()
    path = _safe_under(DATA_DIR, row["crop_path"] if row else None)
    if path is None:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.get("/api/v5/face-samples/{sample_id}/image")
def face_sample_image(sample_id: int) -> FileResponse:
    with connection() as conn:
        row = conn.execute("SELECT crop_path FROM face_samples WHERE id = ?", (sample_id,)).fetchone()
    path = _safe_under(FACES_DIR, row["crop_path"] if row else None)
    if path is None:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.get("/api/v5/vision/cameras/{camera_id}/live-scene")
def live_scene(camera_id: int) -> dict[str, Any]:
    return vision.manager.live_scene(camera_id)


@router.get("/api/v5/vision/cameras/{camera_id}/latest.jpg")
def live_frame(camera_id: int) -> Response:
    frame, at = vision.manager.latest_frame(camera_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="Frame ao vivo indisponível")
    ok, encoded = fi.cv2.imencode(".jpg", frame, [int(fi.cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise HTTPException(status_code=500, detail="Falha ao codificar frame")
    return Response(content=encoded.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Frame-Age": str(max(0.0, time.monotonic() - at))})

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import discovery, go2rtc
from .config import APP_NAME, APP_VERSION, DB_PATH, FRONTEND_DIR, GO2RTC_BROWSER_BASE
from .db import connection, init_db, utc_now
from .models import CameraCreate, CameraOut, CameraUpdate, DiscoveryProbeRequest


def mask_rtsp_url(raw: str) -> tuple[str, bool]:
    """Return a credential-safe URL representation for API responses."""
    try:
        parsed = urlsplit(raw)
        has_credentials = parsed.username is not None or parsed.password is not None
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        if has_credentials:
            host = f"***:***@{host}"
        safe = urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))
        return safe, has_credentials
    except Exception:
        return "rtsp://***", True


def camera_row_to_out(row: sqlite3.Row) -> CameraOut:
    safe_url, has_credentials = mask_rtsp_url(row["rtsp_url"])
    viewer_base = "/__go2rtc_direct__" if GO2RTC_BROWSER_BASE == "direct" else GO2RTC_BROWSER_BASE
    return CameraOut(
        id=row["id"],
        name=row["name"],
        location=row["location"],
        stream_name=row["stream_name"],
        enabled=bool(row["enabled"]),
        rtsp_url_display=safe_url,
        has_credentials=has_credentials,
        sync_status=row["sync_status"],
        sync_error=row["sync_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        viewer_url=f"{viewer_base}/stream.html?src={row['stream_name']}&mode=webrtc,mse,mp4,mjpeg",
    )


def get_camera_row(camera_id: int) -> sqlite3.Row:
    with connection() as conn:
        row = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")
    return row


def set_sync_state(camera_id: int, sync_status: str, sync_error: str | None = None) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE cameras SET sync_status = ?, sync_error = ?, updated_at = ? WHERE id = ?",
            (sync_status, sync_error, utc_now(), camera_id),
        )
        conn.commit()


async def sync_camera(camera_id: int) -> CameraOut:
    row = get_camera_row(camera_id)
    if not row["enabled"]:
        await asyncio.to_thread(go2rtc.delete_stream, row["stream_name"])
        set_sync_state(camera_id, "disabled")
        return camera_row_to_out(get_camera_row(camera_id))

    result = await asyncio.to_thread(go2rtc.upsert_stream, row["stream_name"], row["rtsp_url"])
    if result.ok:
        set_sync_state(camera_id, "ok")
    else:
        set_sync_state(camera_id, "error", result.error)
    return camera_row_to_out(get_camera_row(camera_id))


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with connection() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM cameras ORDER BY id").fetchall()]
    for camera_id in ids:
        try:
            await sync_camera(camera_id)
        except Exception:
            pass
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict:
    db_ok = DB_PATH.exists()
    rtc = await asyncio.to_thread(go2rtc.health)
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "missing",
        "go2rtc": "ok" if rtc.ok else "unavailable",
        "go2rtc_error": rtc.error,
    }


@app.post("/api/discovery/scan")
async def discover_cameras() -> dict:
    with connection() as conn:
        urls = [r["rtsp_url"] for r in conn.execute("SELECT rtsp_url FROM cameras").fetchall()]
    existing_hosts = discovery.hosts_from_rtsp_urls(urls)
    return await discovery.scan_local_network(existing_hosts)


@app.post("/api/discovery/probe")
async def probe_discovered_camera(payload: DiscoveryProbeRequest) -> dict:
    paths = (payload.path,) if payload.path else None
    try:
        result = await asyncio.to_thread(
            discovery.probe_rtsp,
            payload.ip,
            payload.username,
            payload.password,
            payload.port,
            paths,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": result.ok,
        "status_code": result.status_code,
        "auth_required": result.auth_required,
        "path": result.path,
        "error": result.error,
    }


@app.get("/api/cameras", response_model=list[CameraOut])
def list_cameras() -> list[CameraOut]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM cameras ORDER BY name COLLATE NOCASE").fetchall()
    return [camera_row_to_out(row) for row in rows]


@app.get("/api/cameras/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: int) -> CameraOut:
    return camera_row_to_out(get_camera_row(camera_id))


@app.post("/api/cameras", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
async def create_camera(payload: CameraCreate) -> CameraOut:
    now = utc_now()
    stream_name = f"camera_{uuid.uuid4().hex[:12]}"
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO cameras
                (name, location, rtsp_url, stream_name, enabled, sync_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (payload.name, payload.location, payload.rtsp_url, stream_name, int(payload.enabled), now, now),
        )
        conn.commit()
        camera_id = int(cursor.lastrowid)
    return await sync_camera(camera_id)


@app.patch("/api/cameras/{camera_id}", response_model=CameraOut)
async def update_camera(camera_id: int, payload: CameraUpdate) -> CameraOut:
    current = get_camera_row(camera_id)
    values = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not values:
        return camera_row_to_out(current)

    allowed = {"name", "location", "rtsp_url", "enabled"}
    assignments: list[str] = []
    params: list[object] = []
    for key, value in values.items():
        if key not in allowed:
            continue
        assignments.append(f"{key} = ?")
        params.append(int(value) if key == "enabled" else value)
    assignments.extend(["sync_status = 'pending'", "sync_error = NULL", "updated_at = ?"])
    params.extend([utc_now(), camera_id])

    with connection() as conn:
        conn.execute(f"UPDATE cameras SET {', '.join(assignments)} WHERE id = ?", params)
        conn.commit()
    return await sync_camera(camera_id)


@app.post("/api/cameras/{camera_id}/sync", response_model=CameraOut)
async def resync_camera(camera_id: int) -> CameraOut:
    return await sync_camera(camera_id)


@app.post("/api/cameras/sync-all")
async def sync_all_cameras() -> dict:
    with connection() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM cameras ORDER BY id").fetchall()]
    results = []
    for camera_id in ids:
        results.append((await sync_camera(camera_id)).model_dump())
    return {"count": len(results), "cameras": results}


@app.delete("/api/cameras/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(camera_id: int) -> Response:
    row = get_camera_row(camera_id)
    await asyncio.to_thread(go2rtc.delete_stream, row["stream_name"])
    with connection() as conn:
        conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
        conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


if FRONTEND_DIR.exists():
    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(
            FRONTEND_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )

    @app.get("/icon.svg", include_in_schema=False)
    def icon() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "icon.svg", media_type="image/svg+xml")

    @app.get("/styles.css", include_in_schema=False)
    def styles() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "styles.css", media_type="text/css")

    @app.get("/{path:path}", include_in_schema=False)
    def spa_fallback(path: str) -> FileResponse:
        requested = (FRONTEND_DIR / path).resolve()
        if path and requested.is_file() and FRONTEND_DIR.resolve() in requested.parents:
            return FileResponse(requested)
        return FileResponse(FRONTEND_DIR / "index.html")

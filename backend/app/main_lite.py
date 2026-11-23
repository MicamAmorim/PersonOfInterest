"""POI Android: cameras, same-origin playback and continuous recording."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import shutil
import sqlite3
import uuid
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import urlopen

import websockets
from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.requests import HTTPConnection

from . import discovery, go2rtc
from .config import APP_NAME, APP_VERSION, DATA_DIR, FRONTEND_DIR, GO2RTC_API_URL
from .db import connection, init_db, utc_now
from .models import CameraCreate, CameraOut, CameraUpdate, DiscoveryProbeRequest
from .storage_recording import RecorderManager, ensure_schema


class LiteRecorder(RecorderManager):
    reserve_bytes = 2 * 1024**3
    paused_for_space = False

    def _reconcile(self) -> None:
        self.paused_for_space = shutil.disk_usage(DATA_DIR).free < self.reserve_bytes
        if self.paused_for_space:
            for camera_id in list(self.sessions):
                self._stop_session(camera_id)
            self._index_continuous_files()
            return
        super()._reconcile()


recorder = LiteRecorder()
camera_write_lock = asyncio.Lock()
player_assets = {
    "stream.html": "text/html",
    "video-stream.js": "text/javascript",
    "video-rtc.js": "text/javascript",
}
lan_ranges = tuple(ipaddress.IPv4Network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def camera_row(camera_id: int) -> sqlite3.Row:
    with connection() as conn:
        row = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Câmera não encontrada")
    return row


def camera_output(row: sqlite3.Row) -> CameraOut:
    try:
        source = urlsplit(row["rtsp_url"])
        # Drop userinfo, query and fragment. Configured URLs are only read by go2rtc.
        display_url = urlunsplit((source.scheme, source.netloc.rsplit("@", 1)[-1], source.path, "", ""))
        has_credentials = source.username is not None
    except ValueError:
        display_url = "rtsp://…"
        has_credentials = True
    return CameraOut(
        id=row["id"], name=row["name"], location=row["location"], stream_name=row["stream_name"],
        enabled=bool(row["enabled"]), rtsp_url_display=display_url, has_credentials=has_credentials,
        sync_status=row["sync_status"],
        sync_error="Falha ao configurar o fluxo no go2rtc" if row["sync_status"] == "error" else None,
        created_at=row["created_at"], updated_at=row["updated_at"],
        viewer_url="/go2rtc/stream.html?" + urlencode({"src": row["stream_name"], "mode": "mse,mp4"}),
    )


async def sync_camera(camera_id: int) -> CameraOut:
    row = camera_row(camera_id)
    if row["enabled"]:
        result = await asyncio.to_thread(go2rtc.upsert_stream, row["stream_name"], row["rtsp_url"])
        state = "ok" if result.ok else "error"
    else:
        await asyncio.to_thread(go2rtc.delete_stream, row["stream_name"])
        state = "disabled"
    with connection() as conn:
        conn.execute(
            "UPDATE cameras SET sync_status = ?, sync_error = NULL, updated_at = ? WHERE id = ?",
            (state, utc_now(), camera_id),
        )
        conn.commit()
    recorder.notify_change()
    return camera_output(camera_row(camera_id))


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    ensure_schema()
    with connection() as conn:
        camera_ids = [row["id"] for row in conn.execute("SELECT id FROM cameras ORDER BY id")]
    for camera_id in camera_ids:
        await sync_camera(camera_id)
    recorder.start()
    try:
        yield
    finally:
        await asyncio.to_thread(recorder.stop)


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan, openapi_url=None)


def same_origin(client: HTTPConnection) -> bool:
    origin = client.headers.get("origin")
    if not origin:  # Non-browser clients are already scoped by the bind address and tailnet ACL.
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    host = client.headers.get("host", "")
    scheme = {"ws": "http", "wss": "https"}.get(client.url.scheme, client.url.scheme)
    if client.client and client.client.host in {"127.0.0.1", "::1"}:
        # Tailscale Serve rewrites Host and supplies the original authority. Uvicorn
        # leaves client addresses untouched so only a local proxy can set these.
        host = client.headers.get("x-forwarded-host", host)
        scheme = client.headers.get("x-forwarded-proto", scheme)
    return parsed.scheme == scheme and parsed.netloc.lower() == host.lower()


@app.middleware("http")
async def private_api(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not same_origin(request):
            return JSONResponse({"detail": "Origem não autorizada"}, 403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/cameras"):
        return JSONResponse({"detail": "Confira o nome e o endereço RTSP da câmera."}, 422)
    if request.url.path == "/api/discovery/probe":
        return JSONResponse({"detail": "Confira os dados de acesso da câmera."}, 422)
    return await request_validation_exception_handler(request, exc)


@app.get("/api/health")
async def health() -> dict:
    rtc = await asyncio.to_thread(go2rtc.health)
    return {"app": APP_NAME, "version": APP_VERSION, "profile": "lite", "go2rtc": "ok" if rtc.ok else "unavailable"}


def camera_lan_ip() -> str:
    try:
        address = ipaddress.IPv4Address(discovery.get_local_ipv4())
    except ValueError:
        address = None
    if address is None or not any(address in network for network in lan_ranges):
        raise HTTPException(503, "Conecte o servidor à rede local das câmeras e tente novamente.")
    return str(address)


@app.post("/api/discovery/scan")
async def discover_cameras() -> dict:
    local_ip = camera_lan_ip()
    with connection() as conn:
        urls = [row["rtsp_url"] for row in conn.execute("SELECT rtsp_url FROM cameras")]
    return await discovery.scan_local_network(discovery.hosts_from_rtsp_urls(urls), local_ip=local_ip)


@app.post("/api/discovery/probe")
async def probe_discovered_camera(payload: DiscoveryProbeRequest) -> dict:
    camera_lan_ip()
    if payload.port != 554 or any(char.isspace() for char in (payload.path or "")) or any(
        char in payload.username for char in '\r\n'
    ):
        raise HTTPException(422, "Confira os dados de acesso da câmera.")
    paths = (payload.path,) if payload.path else ("/Streaming/Channels/101", *discovery.DEFAULT_RTSP_PATHS)
    try:
        result = await asyncio.to_thread(discovery.probe_rtsp, payload.ip, payload.username, payload.password, 554, paths)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": result.ok, "auth_required": result.auth_required, "path": result.path, "error": result.error}


@app.get("/api/cameras", response_model=list[CameraOut])
def list_cameras() -> list[CameraOut]:
    with connection() as conn:
        return [camera_output(row) for row in conn.execute("SELECT * FROM cameras ORDER BY name COLLATE NOCASE")]


@app.post("/api/cameras", response_model=CameraOut, status_code=201)
async def create_camera(payload: CameraCreate) -> CameraOut:
    async with camera_write_lock:
        now = utc_now()
        with connection() as conn:
            cursor = conn.execute(
                """INSERT INTO cameras(name, location, rtsp_url, stream_name, enabled, sync_status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (payload.name, payload.location, payload.rtsp_url, f"camera_{uuid.uuid4().hex[:12]}",
                 int(payload.enabled), now, now),
            )
            camera_id = cursor.lastrowid
            conn.execute("INSERT INTO recording_settings(camera_id, updated_at) VALUES (?, ?)", (camera_id, now))
            conn.commit()
        return await sync_camera(camera_id)


@app.patch("/api/cameras/{camera_id}", response_model=CameraOut)
async def update_camera(camera_id: int, payload: CameraUpdate) -> CameraOut:
    async with camera_write_lock:
        row = camera_row(camera_id)
        values = payload.model_dump(exclude_none=True)
        if not values:
            return camera_output(row)
        now = utc_now()
        with connection() as conn:
            conn.execute(
                "UPDATE cameras SET name = ?, location = ?, rtsp_url = ?, enabled = ?, updated_at = ? WHERE id = ?",
                (values.get("name", row["name"]), values.get("location", row["location"]),
                 values.get("rtsp_url", row["rtsp_url"]), int(values.get("enabled", row["enabled"])), now, camera_id),
            )
            conn.commit()
        if "rtsp_url" in values or "enabled" in values:
            return await sync_camera(camera_id)
        return camera_output(camera_row(camera_id))


@app.post("/api/cameras/{camera_id}/sync", response_model=CameraOut)
async def resync_camera(camera_id: int) -> CameraOut:
    async with camera_write_lock:
        return await sync_camera(camera_id)


class RecordingSettings(BaseModel):
    mode: Literal["off", "continuous"]
    segment_duration_value: float | None = Field(default=None, gt=0, le=30)


@app.get("/api/recording/settings")
def recording_settings() -> list[dict]:
    return recorder.settings()


@app.patch("/api/recording/settings/{camera_id}")
def set_recording_settings(camera_id: int, payload: RecordingSettings) -> dict:
    camera_row(camera_id)
    values = payload.model_dump(exclude_none=True)
    if "segment_duration_value" in values:
        values["segment_duration_unit"] = "minutes"
    return recorder.update_camera_settings(camera_id, values)


@app.get("/api/recording/status")
def recording_status() -> dict:
    status = recorder.status()
    return {
        "ffmpeg_available": status["ffmpeg_available"], "sessions": status["sessions"],
        "paused_for_space": recorder.paused_for_space,
        "free_bytes": shutil.disk_usage(DATA_DIR).free,
    }


@app.get("/api/recordings")
def list_recordings(camera_id: int | None = None, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    return recorder.list_recordings(camera_id=camera_id, limit=limit)


@app.get("/api/recordings/{recording_id}/file")
def recording_file(recording_id: int) -> FileResponse:
    path = recorder.recording_path(recording_id)
    if path is None:
        raise HTTPException(404, "Gravação não encontrada")
    return FileResponse(path, media_type="video/mp4")


def load_player_asset(asset_name: str) -> bytes:
    with urlopen(f"{GO2RTC_API_URL}/{asset_name}", timeout=4) as response:
        return response.read()


@app.get("/go2rtc/{asset_name}")
async def player_asset(asset_name: str) -> Response:
    if asset_name not in player_assets:
        raise HTTPException(404, "Recurso de vídeo não encontrado")
    try:
        body = await asyncio.to_thread(load_player_asset, asset_name)
    except OSError as exc:
        raise HTTPException(502, "go2rtc indisponível") from exc
    if asset_name == "stream.html":
        # The player only needs local assets and its same-origin video socket.
        csp = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; media-src 'self' blob:; connect-src 'self' ws: wss:; img-src 'self' data:"
        return Response(body, media_type=player_assets[asset_name], headers={"Content-Security-Policy": csp})
    return Response(body, media_type=player_assets[asset_name])


@app.websocket("/go2rtc/api/ws")
async def stream_socket(client: WebSocket) -> None:
    name = client.query_params.get("src", "")
    with connection() as conn:
        row = conn.execute("SELECT 1 FROM cameras WHERE stream_name = ? AND enabled = 1", (name,)).fetchone()
    if row is None or not same_origin(client):
        await client.close(code=1008)
        return

    await client.accept()
    endpoint = urlsplit(GO2RTC_API_URL)
    scheme = "wss" if endpoint.scheme == "https" else "ws"
    upstream_url = f"{scheme}://{endpoint.netloc}/api/ws?src={quote(name, safe='')}"
    try:
        async with websockets.connect(upstream_url, max_size=16 * 1024**2, open_timeout=4) as upstream:
            async def forward_requests() -> None:
                while True:
                    frame = await client.receive()
                    if frame["type"] == "websocket.disconnect":
                        raise WebSocketDisconnect(frame.get("code", 1000))
                    message = frame.get("text")
                    if message is None or len(message) > 4096:
                        continue
                    payload = json.loads(message)
                    if not isinstance(payload, dict) or payload.get("type") not in ("mse", "mp4"):
                        continue
                    await upstream.send(message)

            async def forward_media() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await client.send_bytes(message)
                    else:
                        await client.send_text(message)

            tasks = {asyncio.create_task(forward_requests()), asyncio.create_task(forward_media())}
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except WebSocketDisconnect:
        return
    except (OSError, TimeoutError, ValueError, websockets.exceptions.WebSocketException):
        await client.close(code=1011)
        return
    await client.close(code=1000)


def frontend_file(name: str, *, media_type: str | None = None) -> FileResponse:
    return FileResponse(FRONTEND_DIR / name, media_type=media_type, headers={"Cache-Control": "no-cache"})


@app.get("/")
def index() -> FileResponse:
    return frontend_file("lite.html")


@app.get("/manifest.webmanifest")
def manifest() -> JSONResponse:
    data = json.loads((FRONTEND_DIR / "manifest.webmanifest").read_text(encoding="utf-8"))
    data["description"] = "Câmeras ao vivo e gravações do PersonOfInterest."
    data["shortcuts"] = [{"name": "Gravações", "url": "/?view=recordings"}]
    return JSONResponse(data, media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return frontend_file("lite-sw.js", media_type="text/javascript")


@app.get("/{asset_name}")
def app_asset(asset_name: str) -> FileResponse:
    if asset_name not in {"styles.css", "lite.css", "lite.js", "icon.svg", "v54-pwa.js", "v54-pwa.css"}:
        raise HTTPException(404, "Página não encontrada")
    return frontend_file(asset_name)

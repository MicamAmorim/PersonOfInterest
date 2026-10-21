from __future__ import annotations

import asyncio
from urllib.parse import quote

from fastapi import WebSocket


def install() -> None:
    from . import api_v34, go2rtc
    from .db import connection

    if getattr(api_v34.router, "_poi_browser_ws_authorization", False):
        return

    path_value = "/go2rtc/api/ws"
    api_v34.router.routes[:] = [
        route for route in api_v34.router.routes
        if getattr(route, "path", None) != path_value
    ]

    async def browser_aware_go2rtc_stream_proxy(websocket: WebSocket) -> None:
        src = (websocket.query_params.get("src") or "").strip()
        if not src:
            await websocket.close(code=4400)
            return

        browser_suffix = "_browser"
        is_browser = src.endswith(browser_suffix)
        base_src = src[:-len(browser_suffix)] if is_browser else src
        if not base_src or (src != base_src and src != f"{base_src}{browser_suffix}"):
            await websocket.close(code=4404)
            return

        with connection() as conn:
            row = conn.execute(
                "SELECT stream_name FROM cameras WHERE stream_name = ? AND enabled = 1",
                (base_src,),
            ).fetchone()
        if row is None:
            await websocket.close(code=4404)
            return

        # Only the exact persisted camera stream or its dedicated browser H.264
        # derivative is authorized. Arbitrary go2rtc stream names stay blocked.
        allowed = {str(row["stream_name"]), f"{row['stream_name']}{browser_suffix}"}
        if src not in allowed:
            await websocket.close(code=4404)
            return

        # Browser streams are runtime/lazy resources. Guarantee that the derived
        # stream exists immediately before signaling so a lost/failed startup
        # registration cannot surface as go2rtc's "stream not found" in the UI.
        if is_browser:
            ensure = getattr(go2rtc, "ensure_browser_stream", None)
            if callable(ensure):
                result = await asyncio.to_thread(ensure, base_src)
                if not result.ok:
                    await websocket.close(code=1011)
                    return

        upstream_url = f"ws://127.0.0.1:1984/api/ws?src={quote(src)}"
        await api_v34._bridge_websocket(websocket, upstream_url)

    api_v34.router.add_api_websocket_route(
        path_value,
        browser_aware_go2rtc_stream_proxy,
        name="go2rtc_stream_proxy_browser_aware",
    )
    api_v34.router._poi_browser_ws_authorization = True  # type: ignore[attr-defined]

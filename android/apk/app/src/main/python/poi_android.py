import os
import threading

import uvicorn


_lock = threading.Lock()
_server = None


def run(data_dir, frontend_dir, ffmpeg):
    global _server
    with _lock:
        os.environ.update(
            DATA_DIR=data_dir,
            FRONTEND_DIR=frontend_dir,
            FFMPEG_PATH=ffmpeg,
            GO2RTC_API_URL="http://127.0.0.1:11984",
            POI_RESTREAM_PORT="18554",
            POI_PROFILE="lite",
        )
        from app.main_lite import app

        config = uvicorn.Config(
            app, host="127.0.0.1", port=18080, workers=1, loop="asyncio", http="h11",
            ws="websockets", ws_max_size=4096, proxy_headers=False, access_log=False,
            log_config=None, timeout_graceful_shutdown=3,
        )
        server = uvicorn.Server(config)
        _server = server
        try:
            server.run()
            return server.started
        finally:
            _server = None


def request_stop():
    server = _server
    if server is not None:
        server.should_exit = True

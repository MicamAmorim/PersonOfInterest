from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "PersonOfInterest"
MODEL_SPECS = {
    "yolox_tiny.onnx": (
        "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx",
        1_000_000,
    ),
    "face_detection_yunet_2023mar.onnx": (
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        150_000,
    ),
    "face_recognition_sface_2021dec.onnx": (
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface_2021dec.onnx",
        10_000_000,
    ),
    "osnet_x0_25_msmt17.onnx": (
        "https://huggingface.co/anriha/osnet_x0_25_msmt17/resolve/main/osnet_x0_25_msmt17.onnx?download=true",
        700_000,
    ),
}


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[1]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_data_dir() -> Path:
    explicit = os.getenv("POI_DATA_DIR") or os.getenv("DATA_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()

    if not frozen():
        return (project_root() / "data").resolve()

    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return (base / APP_NAME / "data").resolve()

    xdg = os.getenv("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (base / "personofinterest" / "data").resolve()


def http_json(url: str, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read() or b"{}")
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def poi_health(port: int) -> bool:
    payload = http_json(f"http://127.0.0.1:{port}/api/health")
    return bool(payload and payload.get("app") == APP_NAME)


def go2rtc_health() -> bool:
    return http_json("http://127.0.0.1:1984/api/streams") is not None


def ensure_download(path: Path, url: str, minimum_bytes: int, label: str) -> Path:
    if path.is_file() and path.stat().st_size >= minimum_bytes:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    try:
        part.unlink(missing_ok=True)
        print(f"Baixando {label} (uma única vez)...")
        request = urllib.request.Request(url, headers={"User-Agent": "PersonOfInterest"})
        with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        if part.stat().st_size < minimum_bytes:
            raise RuntimeError(f"download incompleto de {label}")
        part.replace(path)
        return path
    except Exception:
        part.unlink(missing_ok=True)
        raise


def resolve_models(data_dir: Path, resources: Path) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for name, (url, minimum) in MODEL_SPECS.items():
        bundled = resources / "models" / name
        if bundled.is_file() and bundled.stat().st_size >= minimum:
            resolved[name] = bundled
            continue
        local = data_dir / "models" / name
        resolved[name] = ensure_download(local, url, minimum, name)
    return resolved


def configure_environment(data_dir: Path, resources: Path, models: dict[str, Path]) -> None:
    frontend = resources / "frontend"
    if not frontend.is_dir():
        raise RuntimeError(f"Frontend empacotado não encontrado: {frontend}")

    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["FRONTEND_DIR"] = str(frontend)
    os.environ["GO2RTC_API_URL"] = "http://127.0.0.1:1984"
    os.environ["GO2RTC_BROWSER_BASE"] = "direct"
    os.environ["VISION_MODEL_PATH"] = str(models["yolox_tiny.onnx"])
    os.environ["FACE_DETECTOR_MODEL_PATH"] = str(models["face_detection_yunet_2023mar.onnx"])
    os.environ["FACE_RECOGNIZER_MODEL_PATH"] = str(models["face_recognition_sface_2021dec.onnx"])
    os.environ["BODY_REID_MODEL_PATH"] = str(models["osnet_x0_25_msmt17.onnx"])


def go2rtc_binary(resources: Path) -> Path:
    name = "go2rtc.exe" if os.name == "nt" else "go2rtc"
    binary = resources / "bin" / name
    if not binary.is_file():
        raise RuntimeError(f"go2rtc empacotado não encontrado: {binary}")
    if os.name != "nt":
        try:
            binary.chmod(binary.stat().st_mode | 0o111)
        except OSError:
            pass
    return binary


def write_go2rtc_config(data_dir: Path) -> Path:
    path = data_dir / "go2rtc.runtime.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """api:\n  listen: \":1984\"\nrtsp:\n  listen: \":8554\"\nwebrtc:\n  listen: \":8555\"\nstreams: {}\nlog:\n  level: info\n""",
        encoding="utf-8",
    )
    return path


def start_go2rtc(resources: Path, data_dir: Path) -> tuple[subprocess.Popen | None, object | None]:
    if go2rtc_health():
        print("go2rtc já está online em :1984; reutilizando a instância existente.")
        return None, None

    binary = go2rtc_binary(resources)
    config = write_go2rtc_config(data_dir)
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_handle = (log_dir / "go2rtc-packaged.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        [str(binary), "-c", str(config)],
        cwd=str(data_dir),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )

    for _ in range(50):
        if process.poll() is not None:
            log_handle.close()
            raise RuntimeError("go2rtc encerrou durante a inicialização")
        if go2rtc_health():
            return process, log_handle
        time.sleep(0.2)

    process.terminate()
    log_handle.close()
    raise RuntimeError("go2rtc não respondeu na porta 1984")


def stop_go2rtc(process: subprocess.Popen | None, log_handle: object | None) -> None:
    if process is not None and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
    if log_handle is not None:
        try:
            log_handle.close()  # type: ignore[attr-defined]
        except Exception:
            pass


def open_when_ready(port: int) -> None:
    for _ in range(120):
        if poi_health(port):
            webbrowser.open(f"http://127.0.0.1:{port}")
            return
        time.sleep(0.25)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PersonOfInterest packaged launcher")
    parser.add_argument("--no-browser", action="store_true", help="não abrir o navegador automaticamente")
    parser.add_argument("--port", type=int, default=int(os.getenv("POI_PORT", "8080")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    port = max(1, min(65535, int(args.port)))

    if poi_health(port):
        print(f"PersonOfInterest já está online em http://127.0.0.1:{port}")
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{port}")
        return 0

    resources = resource_root()
    data_dir = default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    models = resolve_models(data_dir, resources)
    configure_environment(data_dir, resources, models)

    # Source-mode convenience for developers. PyInstaller supplies this path in
    # frozen builds through Analysis(pathex=...).
    if not frozen():
        backend = project_root() / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))

    rtc_process: subprocess.Popen | None = None
    rtc_log: object | None = None
    try:
        rtc_process, rtc_log = start_go2rtc(resources, data_dir)

        from app.main import app
        import uvicorn

        if not args.no_browser:
            threading.Thread(target=open_when_ready, args=(port,), daemon=True).start()

        print(f"=== {APP_NAME} ===")
        print(f"Dados: {data_dir}")
        print(f"Servidor: http://127.0.0.1:{port}")
        print("Pressione Ctrl+C para encerrar.")

        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        stop_go2rtc(rtc_process, rtc_log)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(main())

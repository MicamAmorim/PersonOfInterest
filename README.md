# PersonOfInterest

Local-first IP camera dashboard. V1 establishes the NVR foundation: RTSP camera registration, persistent SQLite configuration, go2rtc streaming and a responsive installable PWA. **Windows native is the primary development path; Docker is optional.**

> Facial recognition, identity clustering, event history and push notifications are deliberately left for later versions. V1 builds the stable camera/streaming base first.

## V1

- FastAPI backend
- Persistent SQLite database
- Add, edit, enable/disable, re-sync and delete cameras
- RTSP credentials remain local and are masked in API responses
- go2rtc stream synchronization
- WebRTC playback with MSE/MP4/MJPEG fallbacks
- Responsive PWA for desktop and mobile
- Native Windows setup/start scripts
- Docker Compose remains available as an optional deployment
- Backend/database/go2rtc health status

## Quick start — Windows, no Docker

Requirement: **Python 3.11+** on Windows 10/11.

```powershell
git clone https://github.com/MicamAmorim/PersonOfInterest.git
cd PersonOfInterest
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

`setup.ps1` creates `.venv`, installs the Python dependencies and downloads the official 64-bit Windows build of go2rtc into `bin/`. The go2rtc project publishes `go2rtc_win64.zip` for Windows 10+ 64-bit.

After startup the browser opens automatically at:

```text
http://localhost:8080
```

To start later, only run:

```powershell
.\start.ps1
```

To start without opening the browser:

```powershell
.\start.ps1 -NoBrowser
```

Press **Ctrl+C** in the PowerShell window to stop the backend and go2rtc.

The SQLite database is stored at `data/person_of_interest.db` and is ignored by Git.

### PowerShell execution policy

If Windows blocks local scripts, either use the `powershell -ExecutionPolicy Bypass -File ...` commands above or, for the current terminal only:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

## Add a camera

Open **Nova câmera** and paste the camera RTSP address, for example:

```text
rtsp://user:password@192.168.1.50:554/stream1
```

The RTSP path varies by manufacturer and model. After saving, PersonOfInterest never returns the original credentials through its API; the UI only sees a masked form such as `rtsp://***:***@192.168.1.50:554/stream1`.

In native mode go2rtc listens on `1984/TCP` and WebRTC uses `8555/TCP+UDP`. The backend/PWA listens on `8080/TCP`.

## Architecture

```text
IP cameras (RTSP)
        |
        v
     go2rtc <----- FastAPI ----- SQLite
        |              |
        |              v
        +--------> Browser / PWA
                    :8080
```

The browser loads the PersonOfInterest UI from FastAPI on port `8080`; camera playback is served by the local go2rtc process on port `1984`.

## Optional Docker mode

Docker is not required. It remains available for reproducible deployments:

```powershell
docker compose up -d --build
```

Then open `http://localhost:8080`. Docker mode uses Caddy as a same-origin proxy and keeps go2rtc internal except for WebRTC media ports.

## Tailscale

The intended remote-access model is a trusted LAN/tailnet, not public port-forwarding. Native LAN access works by using the machine's IP instead of `localhost`. Before treating remote PWA access as production-ready, the native mode will gain the same-origin HTTPS proxy used for Tailscale/Web Push; that is intentionally separate from this first local V1 test.

## Project layout

```text
backend/             FastAPI + SQLite + go2rtc integration
frontend/            installable responsive PWA
infra/go2rtc/        go2rtc configuration
bin/                 local go2rtc executable (ignored by Git)
data/                local SQLite data (ignored by Git)
setup.ps1             one-time Windows bootstrap
start.ps1             native Windows launcher
Caddyfile             Docker same-origin gateway
docker-compose.yml    optional container stack
tests/                backend unit tests
```

## Validation

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Roadmap

**V2 — vision events:** person detection/tracking, useful-face detection, snapshots and event timeline.

**V3 — identity:** local face embeddings, known/unknown matching, unknown clustering and the “Who is this?” classification flow with retroactive identity assignment.

**V4 — alerts:** Web Push, unknown-person notifications with photos, cooldowns and camera/time rules.

## Security

PersonOfInterest will ultimately contain sensitive surveillance and biometric information. Keep it on trusted infrastructure, use strong camera credentials, keep `data/` out of source control and back up the local database securely.

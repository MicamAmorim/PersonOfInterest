# PersonOfInterest

Local-first IP camera surveillance app. V1 established the NVR foundation; **V2 adds local computer vision, person tracking, face detection, event snapshots/timeline and optional PTZ auto-follow**. Windows native remains the primary development path; Docker is optional.

## V2

- FastAPI + SQLite backend
- RTSP camera registration and local discovery
- go2rtc live streaming
- Local person detection with OpenCV
- Per-camera tracking IDs
- Frontal-face detection associated with tracked people
- Event snapshots stored under `data/events/`
- Timeline filtered by camera
- Live tracking boxes over the selected camera
- Optional **Acompanhar pessoa** mode: select a tracked person or let the app follow the most prominent person
- Semi-transparent PTZ joystick in the lower-right corner of the expanded camera viewer
- PTZ control through ONVIF when supported by the camera
- Responsive installable PWA

> V3 remains responsible for identity: face embeddings, known/unknown matching, clustering and retroactive person naming.

## Quick start — Windows, no Docker

Requirement: **Python 3.11+** on Windows 10/11.

```powershell
git clone https://github.com/MicamAmorim/PersonOfInterest.git
cd PersonOfInterest
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

On an existing V1 installation, update and start normally:

```powershell
git pull
.\start.ps1
```

`start.ps1` checks for the new OpenCV/Numpy V2 dependencies and installs them from `backend/requirements.txt` if needed.

Open:

```text
http://localhost:8080
```

## Camera discovery

Click **Descobrir câmeras**. PersonOfInterest scans only the computer's local `/24` subnet and surfaces devices exposing RTSP (`554`) or ONVIF (`8899`). It tests a real RTSP `DESCRIBE` before allowing a discovered camera to be saved.

Credentials remain local. The original RTSP URL is stored only in SQLite and API responses mask its credentials.

## Vision pipeline

```text
Camera RTSP
   |
   +--> go2rtc --> browser live view
   |
   +--> OpenCV worker
          |
          +--> person detector
          +--> centroid/IoU tracker
          +--> face detector
          +--> event snapshot
          +--> SQLite timeline
          +--> optional PTZ auto-follow
```

The current V2 detector is intentionally lightweight and CPU-friendly so the system runs without CUDA. It is an interchangeable component; a YOLO/ONNX detector can replace it later without changing the event/timeline model.

## Tracking and auto-follow

Open a camera. Detected people appear as boxes with IDs (`#1`, `#2`, ...). Clicking a box selects that track. Enable **Acompanhar pessoa** to let the camera keep the selected person near the image center. If no track is selected, the largest visible person is used.

Auto-follow uses a dead zone and movement cooldown so the camera does not continuously oscillate around the center.

Manual PTZ always remains available through the small joystick in the lower-right corner of the expanded video. Starting manual joystick movement disables auto-follow for that moment.

## Timeline

The **Timeline** view shows saved person events with camera, timestamp, tracking ID, face-detected indicator and snapshot.

Data is stored locally:

```text
data/person_of_interest.db
data/events/YYYY-MM-DD/<camera-id>/...
```

## PTZ compatibility

The V2 PTZ layer first uses standard ONVIF capabilities/profile discovery and `ContinuousMove`/`Stop`. Many iCSee/XMEye/Xiongmai cameras expose ONVIF on port `8899`, but firmware compatibility varies. The UI reports PTZ availability per camera; vendor-specific DVRIP/Sofia fallback can be added for devices whose video works while ONVIF PTZ is incomplete.

## Ports

Native mode:

```text
8080/tcp       PersonOfInterest API + PWA
1984/tcp       go2rtc API/player
8554/tcp       go2rtc local RTSP
8555/tcp+udp   WebRTC
```

## Optional Docker mode

Docker is not required:

```powershell
docker compose up -d --build
```

## Tailscale

The intended remote-access model is a trusted LAN/tailnet, not public port-forwarding. For external access use Tailscale rather than exposing the camera or PersonOfInterest ports directly to the public internet.

## Validation

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Frontend syntax is also checked in CI with `node --check`.

## Branches

Before starting V2, the stable V1 state was preserved at:

```text
backup/v1-stable-2026-10-17
```

Development work was staged on `v2-work` before promotion to `main`.

## Roadmap

**V3 — identity:** local face embeddings, known/unknown matching, unknown clustering and the “Who is this?” classification flow with retroactive identity assignment.

**V4 — alerts:** Web Push, unknown-person notifications with photos, cooldowns and camera/time rules.

## Security

PersonOfInterest stores surveillance data and will later store biometric identifiers. Keep it on trusted infrastructure, use strong camera credentials, keep `data/` out of source control and back up the local database securely.

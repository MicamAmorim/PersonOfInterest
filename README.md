# PersonOfInterest

Local-first IP camera surveillance app for Windows. The current V4 stack combines live RTSP/WebRTC viewing, person detection/tracking, PTZ auto-follow, local face identity, unknown-person clustering, timeline/history, Web Push and configurable alert rules.

## Current capabilities

- FastAPI + SQLite backend
- go2rtc local restreaming
- camera discovery and credential-safe registration
- YOLOX-Tiny ONNX person detection
- tracking + PTZ auto-follow + Home preset
- YuNet face detection + SFace embeddings
- known/unknown matching and clustering
- **Quem é esta pessoa?** workflow with retroactive history association
- timeline filters by camera, person, date, time and face presence
- single, multiple and bulk timeline deletion
- local Web Push subscriptions
- alert rules by camera / known person / unknown person / time window / cooldown
- statistics by camera and known person
- same-origin WebRTC proxy designed for HTTPS/Tailscale/PWA use
- camera audio + optional browser microphone backchannel when the device supports it

All camera credentials, face crops, embeddings, history, Web Push subscriptions and VAPID private key remain under local `data/` and are ignored by Git.

## Quick start — Windows

Requirement: Python 3.11+ and Windows 10/11.

```powershell
git clone https://github.com/MicamAmorim/PersonOfInterest.git
cd PersonOfInterest
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Existing installation:

```powershell
git pull
.\start.ps1
```

The first V3/V4 start installs Web Push dependencies and downloads three local models if missing:

- `yolox_tiny.onnx`
- `face_detection_yunet_2023mar.onnx`
- `face_recognition_sface_2021dec.onnx`

Open locally:

```text
http://localhost:8080
```

## V3 identity pipeline

```text
person event snapshot
        ↓
      YuNet
        ↓
aligned face crop
        ↓
      SFace
        ↓
L2-normalized embedding
        ↓
known samples? ── yes ──> person_id
        │
        no
        ↓
nearest open unknown cluster
        ↓
cluster existing / create new
```

The identity worker also indexes older V2 snapshots in the background. Unknown groups appear in **Pessoas → Quem é esta pessoa?**. Assigning a cluster to a new or existing person updates all matching historical events in that cluster, and its samples become known references for future detections.

Local data:

```text
data/person_of_interest.db
data/events/...
data/faces/...
data/models/...
data/vapid/...
```

## V4 alerts

Open **Alertas** and activate notifications on each browser/PWA where you want to receive them. Rules support:

- all cameras or one camera;
- any person, a known person, or unknown persons;
- optional time windows, including windows that cross midnight such as `23:00–06:00`;
- per-rule cooldown;
- all days by default.

Example:

```text
Nome: Desconhecido nos fundos à noite
Câmera: Fundos
Quem: Desconhecidos
De: 23:00
Até: 06:00
Cooldown: 5 min
```

Web Push is standards-based. The server generates its own local VAPID keypair on first use.

## Tailscale + mobile PWA

PersonOfInterest is intended to be exposed to your **tailnet**, not directly to the public internet.

With the app running, open another PowerShell in the project folder:

```powershell
.\tailscale-serve.ps1
```

This configures the current Tailscale Serve HTTPS reverse proxy to `localhost:8080` in the background. Check it later with:

```powershell
.\tailscale-serve.ps1 -Status
```

Disable it with:

```powershell
.\tailscale-serve.ps1 -Off
```

Open the `https://...ts.net` URL printed by Tailscale on your phone. The PWA, WebRTC signaling, Web Push and microphone controls remain same-origin through the PersonOfInterest backend.

### Install on Android

Open the Tailscale HTTPS URL in Chrome/Edge and choose **Instalar app / Adicionar à tela inicial**.

### Install on iPhone/iPad

Open the HTTPS URL, use **Compartilhar → Adicionar à Tela de Início**, then launch PersonOfInterest from the Home Screen. iOS/iPadOS Web Push is available to installed Home Screen web apps on supported versions; request notification permission from the installed app.

## Camera audio

Both speaker/listen and microphone/talkback are muted by default. The viewer enables them only after explicit user action. Talkback depends on the individual camera firmware accepting the DVRIP/RTSP backchannel.

## Ports

Local process ports:

```text
8080/tcp       PersonOfInterest API + PWA + WebSocket proxy
1984/tcp       go2rtc local API (browser no longer needs direct access)
8554/tcp       go2rtc local RTSP
8555/tcp+udp   WebRTC media transport
```

Through Tailscale Serve, the browser/PWA uses the HTTPS PersonOfInterest origin. WebRTC media candidates can still use the tailnet interface directly.

## Validation

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Safety branches

Stable checkpoints kept before major work:

```text
backup/v1-stable-2026-10-17
backup/v2.4-stable-before-v3-v4
```

V3/V4 development is staged on:

```text
v3-v4-work
```

## Privacy and security

Face embeddings are biometric identifiers. Keep `data/` private, use strong camera passwords, restrict Tailscale access with your tailnet ACLs, avoid public port forwarding/Funnel for this deployment, and secure backups of the SQLite database and face data.

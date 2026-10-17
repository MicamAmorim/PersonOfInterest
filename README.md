# PersonOfInterest

Local-first IP camera dashboard. The V1 establishes the NVR foundation: RTSP camera registration, persistent SQLite configuration, go2rtc streaming, a responsive installable PWA and a Docker Compose deployment ready for LAN/Tailscale access.

> Facial recognition, identity clustering, event history and push notifications are deliberately left for later versions. V1 builds the stable camera/streaming base first.

## V1

- FastAPI backend
- Persistent SQLite database
- Add, edit, enable/disable, re-sync and delete cameras
- RTSP credentials remain local and are masked in API responses
- go2rtc stream synchronization
- WebRTC playback with MSE/MP4/MJPEG fallbacks
- Responsive PWA for desktop and mobile
- Caddy same-origin gateway
- Docker Compose startup
- Backend/database/go2rtc health status

## Start locally

Requirements: Docker Desktop (Windows/macOS) or Docker Engine + Docker Compose (Linux).

```bash
git clone https://github.com/MicamAmorim/PersonOfInterest.git
cd PersonOfInterest
docker compose up -d --build
```

Open:

```text
http://localhost:8080
```

Logs:

```bash
docker compose logs -f
```

Stop:

```bash
docker compose down
```

The database is persisted at `data/person_of_interest.db` and is ignored by Git.

## Add a camera

Open **Nova câmera** and paste the camera RTSP address, for example:

```text
rtsp://user:password@192.168.1.50:554/stream1
```

The RTSP path varies by manufacturer and model. After saving, PersonOfInterest never returns the original credentials through its API; the UI only sees a masked form such as `rtsp://***:***@192.168.1.50:554/stream1`.

If playback fails, verify camera reachability, RTSP enablement, credentials and path, then inspect:

```bash
docker compose logs go2rtc
```

## Architecture

```text
IP cameras (RTSP)
        |
        v
     go2rtc <----- FastAPI ----- SQLite
        |              |
        v              |
      Caddy  <----------+
        |
        v
 Browser / PWA
```

The go2rtc HTTP API is not published directly. The browser reaches its player through Caddy at `/go2rtc/`. WebRTC media ports `8555/tcp` and `8555/udp` are published; the player can fall back to browser-friendly streaming through the gateway.

## Tailscale

This project is intended to stay on a trusted LAN/tailnet. Do not port-forward it directly to the public internet. For remote access, point **Tailscale Serve** to the local app at `http://127.0.0.1:8080`. Check the syntax supported by your installed Tailscale version with:

```bash
tailscale serve --help
```

HTTPS is recommended when installing the PWA on other devices.

## Project layout

```text
backend/            FastAPI + SQLite + go2rtc integration
frontend/           installable responsive PWA
infra/go2rtc/       go2rtc configuration
Caddyfile            same-origin gateway
docker-compose.yml   local stack
tests/               backend unit tests
```

## Validation

```bash
python -m compileall backend/app
python -m unittest discover -s tests -v
```

## Roadmap

**V2 — vision events:** person detection/tracking, useful-face detection, snapshots and event timeline.

**V3 — identity:** local face embeddings, known/unknown matching, unknown clustering and the “Who is this?” classification flow with retroactive identity assignment.

**V4 — alerts:** Web Push, unknown-person notifications with photos, cooldowns and camera/time rules.

## Security

PersonOfInterest will ultimately contain sensitive surveillance and biometric information. Keep it on trusted infrastructure, use strong camera credentials, keep `data/` out of source control and back up the local database securely.

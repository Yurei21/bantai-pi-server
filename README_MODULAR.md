# Bantai Pi Server (Modular v2.0)

Modular architecture for dual CSI cameras with WebRTC streaming and rolling recording.

## Architecture
```
bantai-server/
├── app.py              # Main application entry
├── config/             # Configuration
├── core/               # Core utilities (connection manager)
├── cameras/            # Dual camera pipelines
├── recording/          # Rolling clip recorder (H.264)
├── streaming/          # WebRTC streaming
├── api/                # API routes & WebSocket endpoints
└── clips/              # Recorded clips storage
```

## Features
- **Dual CSI Camera Pipelines**: Separate processing pipelines for cam0 and cam1
- **Rolling Recording**: When triggered by Flutter app, records separate clips for each camera with coherent naming (`cam0_YYYYMMDD_HHMMSS_h264.mp4`, `cam1_YYYYMMDD_HHMMSS_h264.mp4`)
- **H.264 Encoding**: Both streaming (WebRTC) and recording use H.264
- **WebRTC to Cloudflare TURN**: Ready for TURN server configuration
- **Flutter App Compatible**: WebSocket control API

## Quick Start
```bash
./start_server_modular.sh
```

Server runs on `http://0.0.0.0:8000`

## API Endpoints

### WebSocket Control
Connect to `ws://<ip>:8000/ws/control`

Commands:
```json
{"command": "start_cameras"}      // Start both camera pipelines
{"command": "start_rolling"}      // Start rolling recording on both cameras (separate clips)
{"command": "stop_rolling"}       // Stop rolling recording
{"command": "start_streaming"}    // Prepare for WebRTC streaming
{"command": "get_status"}         // Get server status
```

### WebRTC Streaming
1. Connect to WebSocket and send `start_streaming`
2. POST offer to `http://<ip>:8000/offer` with WebRTC SDP
3. Get answer with both camera tracks (H.264 encoded)

### HTTP Endpoints
- `GET /` - Web interface
- `GET /health` - Health check
- `GET /api/status` - Status
- `GET /api/clips` - List recorded clips
- `GET /stream/mjpeg/{camera_id}` - MJPEG preview (0 or 1)

## Exposing the Pi server with Cloudflare Tunnel

`cloudflared` runs as a separate service on the Raspberry Pi; the Python application does not create a Tunnel. Use a remotely managed Tunnel so the connector can reconnect automatically and configuration stays in Cloudflare.

1. Install `cloudflared` on Raspberry Pi OS using Cloudflare's [official installation instructions](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/).
2. In Cloudflare Zero Trust, create a new Tunnel under **Networking > Tunnels**. Choose the Linux architecture for the Pi and run the generated install command **on the Pi**. Treat the command and token as secrets; do not commit or share them. Do not reuse the PC's Tunnel token.
3. In **Access controls > Applications**, create a **Self-hosted** application for the public hostname and add an Allow policy restricted to your email or identity. Create the Access application before publishing the hostname.
4. In the Tunnel's **Routes**, add a **Published application** route using that same hostname and service URL `http://localhost:8000`.
5. Start this server on the Pi. Confirm the Tunnel reports **Healthy**, then test the hostname from a private browser window: it should prompt for Cloudflare Access before showing the server.

This Tunnel route exposes HTTP/WebSocket signaling and API access without home-router port forwarding. It does **not** proxy WebRTC media packets or make them traverse the Tunnel. Cloudflare Realtime SFU publishing/subscription must be configured separately for internet video delivery. Restrict API access and never put SFU app secrets in browser code.

### SFU credentials

Copy `.env.example` to `.env` on the Pi and set `CF_SFU_APP_ID` and `CF_SFU_APP_SECRET` locally. `.env` is ignored by Git. These are server-side credentials; never put them in Flutter, the PC viewer, or source control. The Pi must have outbound internet access to Cloudflare Realtime. The PC's two ML pipelines can subscribe to the separate `cam0` and `cam1` tracks from the SFU; the Tunnel is for authenticated signaling/API only.

`/offer` remains direct Pi-to-client WebRTC for local clients. Remote ML uses separate SFU endpoints: `POST /api/sfu/publish` publishes `cam0` and `cam1`; the PC subscriber calls `POST /api/sfu/subscribe` and `PUT /api/sfu/subscribe/{subscriber_session_id}/answer`. The Pi proxies all SFU API calls and retains the App Secret. Protect these endpoints with the Cloudflare Access application and a service-token policy; never publish them without Access. The PC subscriber requires Access service-token credentials configured only in its local `.env`.

In the PC repository, set `PI_API_URL` to the Access-protected Pi hostname and configure `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` in existing `docker/.env`. Run from repository root: `docker compose --env-file docker/.env -f docker/docker-compose.yml up --build -d`. The subscriber publishes received `cam0` and `cam1` as local RTSP streams at `rtsp://rtsp-server:8554/cam0` and `/cam1`; the orchestrator defaults to these paths. Keep Cloudflare Realtime media on its WebRTC connection; Tunnel carries signaling only.

See Cloudflare's [Tunnel setup guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/) and [Access self-hosted application guide](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/).

## Flutter App Integration
When Flutter app sends payload to turn on stream:
1. Send `{"command": "start_streaming"}` via WebSocket
2. Initiate WebRTC connection to `/offer` endpoint
3. To start rolling clips: Send `{"command": "start_rolling"}` via WebSocket

Each camera records to separate files with coherent naming in `clips/` directory.

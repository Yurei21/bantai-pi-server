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

## Flutter App Integration
When Flutter app sends payload to turn on stream:
1. Send `{"command": "start_streaming"}` via WebSocket
2. Initiate WebRTC connection to `/offer` endpoint
3. To start rolling clips: Send `{"command": "start_rolling"}` via WebSocket

Each camera records to separate files with coherent naming in `clips/` directory.

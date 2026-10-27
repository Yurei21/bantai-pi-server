# Bantai Pi Server

Local server for Raspberry Pi to connect with Flutter app via hotspot. Supports:
- WebSocket control for commands (start rolling, stop rolling)
- WebRTC streaming of two CSI/camera feeds to Cloudflare TURN server
- Live camera view through web interface
- REST API for status

## Quick Start
```bash
./start_server.sh
```

Server runs on `http://0.0.0.0:8000`

## Endpoints
- `GET /` - Web interface
- `WS /ws/control` - Control WebSocket for commands
- `WS /ws/camera/{id}` - MJPEG stream per camera
- `POST /offer` - WebRTC offer/answer for P2P streaming
- `GET /health` - Health check
- `GET /api/status` - Server status

## Commands (via WebSocket)
```json
{"command": "start_rolling"}
{"command": "stop_rolling"}
{"command": "start_streaming"}
{"command": "get_status"}
```

#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import socket
from typing import List, Optional

import cv2
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import numpy as np

from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaBlackhole, MediaRelay
from av import VideoFrame
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bantai-server")

app = FastAPI(title="Bantai Pi Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.control_clients: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.control_clients:
            self.control_clients.remove(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except:
            pass

manager = ConnectionManager()

# Camera configuration
CAMERA_DEVICES = ["/dev/video0", "/dev/video1"]
pcs = set()
relay = MediaRelay()

class CameraStreamTrack(VideoStreamTrack):
    def __init__(self, camera_index=0):
        super().__init__()
        self.camera_index = camera_index
        self.cap = None
        self._start()

    def _start(self):
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            logger.info(f"Started camera {self.camera_index}")
        except Exception as e:
            logger.error(f"Failed to start camera {self.camera_index}: {e}")

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        if self.cap is None or not self.cap.isOpened():
            # Return black frame
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        else:
            ret, frame = self.cap.read()
            if not ret:
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            else:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

@app.get("/")
async def root():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Bantai Pi Server</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background: #1e1e1e; color: #fff; }
            .container { max-width: 1200px; margin: 0 auto; }
            .controls { margin: 20px 0; }
            button { padding: 10px 20px; margin: 5px; font-size: 16px; cursor: pointer; }
            .status { padding: 10px; background: #333; border-radius: 5px; margin: 10px 0; }
            .video-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
            video { width: 100%; background: #000; }
            @media (max-width: 768px) {
                .video-grid { grid-template-columns: 1fr; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 Bantai Pi Server</h1>
            <div class="status" id="status">Status: Disconnected</div>
            <div class="controls">
                <button onclick="startRolling()">🎯 Start Rolling</button>
                <button onclick="stopRolling()">⏹️ Stop Rolling</button>
                <button onclick="startStreaming()">📡 Start WebRTC Streaming</button>
                <button onclick="getStatus()">📊 Get Status</button>
            </div>
            <div class="video-grid">
                <div>
                    <h3>Camera 0</h3>
                    <video id="video0" autoplay playsinline muted></video>
                </div>
                <div>
                    <h3>Camera 1</h3>
                    <video id="video1" autoplay playsinline muted></video>
                </div>
            </div>
        </div>
        <script>
            let ws = null;
            const statusDiv = document.getElementById('status');
            
            function connect() {
                ws = new WebSocket(`ws://${location.host}/ws/control`);
                ws.onopen = () => {
                    statusDiv.textContent = 'Status: Connected';
                    console.log('Connected');
                };
                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    console.log('Message:', data);
                    statusDiv.textContent = `Status: ${data.type} - ${JSON.stringify(data)}`;
                };
                ws.onclose = () => {
                    statusDiv.textContent = 'Status: Disconnected';
                    setTimeout(connect, 2000);
                };
            }
            
            function startRolling() {
                if (ws) ws.send(JSON.stringify({command: 'start_rolling'}));
            }
            function stopRolling() {
                if (ws) ws.send(JSON.stringify({command: 'stop_rolling'}));
            }
            function startStreaming() {
                if (ws) ws.send(JSON.stringify({command: 'start_streaming'}));
            }
            function getStatus() {
                if (ws) ws.send(JSON.stringify({command: 'get_status'}));
            }
            
            connect();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.websocket("/ws/control")
async def websocket_control(websocket: WebSocket):
    await manager.connect(websocket)
    manager.control_clients.append(websocket)
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to Bantai Pi Server",
            "cameras": CAMERA_DEVICES
        })
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                command = message.get("command")
                logger.info(f"Received command: {command}")
                
                if command == "start_rolling":
                    await websocket.send_json({
                        "type": "rolling_started",
                        "message": "Rolling mechanism started",
                        "timestamp": time.time()
                    })
                    await manager.broadcast({"type": "event", "event": "rolling_started"})
                
                elif command == "stop_rolling":
                    await websocket.send_json({
                        "type": "rolling_stopped", 
                        "message": "Rolling mechanism stopped",
                        "timestamp": time.time()
                    })
                    await manager.broadcast({"type": "event", "event": "rolling_stopped"})
                
                elif command == "start_streaming":
                    await websocket.send_json({
                        "type": "streaming_started",
                        "message": "WebRTC streaming initiated",
                        "turn_server": "cloudflare", # Configure as needed
                        "cameras": ["cam0", "cam1"],
                        "timestamp": time.time()
                    })
                    await manager.broadcast({"type": "event", "event": "streaming_started"})
                
                elif command == "get_status":
                    await websocket.send_json({
                        "type": "status",
                        "rolling": False,
                        "streaming": False,
                        "cameras_available": len([d for d in CAMERA_DEVICES if os.path.exists(d)]),
                        "uptime": time.time()
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown command: {command}"
                    })
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
    except WebSocketDisconnect:
        await manager.disconnect(websocket)

@app.websocket("/ws/camera/{camera_id}")
async def websocket_camera(websocket: WebSocket, camera_id: int):
    await websocket.accept()
    try:
        cap = cv2.VideoCapture(camera_id)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 15)
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            # Encode frame as JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            await websocket.send_bytes(buffer.tobytes())
            await asyncio.sleep(0.066)  # ~15 FPS
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Camera {camera_id} error: {e}")
    finally:
        if 'cap' in locals():
            cap.release()

@app.post("/offer")
async def offer(request: dict):
    offer = RTCSessionDescription(sdp=request["sdp"], type=request["type"])
    
    pc = RTCPeerConnection()
    pcs.add(pc)
    
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info(f"Connection state is {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)
    
    # Add camera tracks
    for i in range(min(2, len(CAMERA_DEVICES))):
        if os.path.exists(f"/dev/video{i}") or i < 2:
            try:
                video_track = CameraStreamTrack(camera_index=i)
                pc.addTrack(video_track)
                logger.info(f"Added track for camera {i}")
            except Exception as e:
                logger.error(f"Failed to add camera {i}: {e}")
    
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "cameras": [{"device": f"/dev/video{i}", "exists": os.path.exists(f"/dev/video{i}")} for i in range(4)],
        "connections": len(manager.active_connections)
    }

@app.get("/api/status")
async def api_status():
    return {
        "server": "running",
        "ip": socket.gethostbyname(socket.gethostname()),
        "cameras": [d for d in CAMERA_DEVICES if os.path.exists(d)],
        "timestamp": time.time()
    }

if __name__ == "__main__":
    logger.info("Starting Bantai Pi Server...")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

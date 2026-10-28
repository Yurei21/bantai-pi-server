import json
import logging
import time
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
import cv2

from core.manager import manager
from cameras.pipeline import camera_manager
from recording.recorder import recorder_manager
from streaming.webrtc import webrtc_manager
from config.settings import CAMERA_DEVICES, CLIPS_DIR

logger = logging.getLogger("bantai-server")
router = APIRouter()

@router.get("/")
async def root():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Bantai Pi Server - Dual Camera</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background: #1e1e1e; color: #fff; }
            .container { max-width: 1400px; margin: 0 auto; }
            .controls { margin: 20px 0; display: flex; flex-wrap: wrap; gap: 10px; }
            button { padding: 10px 20px; font-size: 16px; cursor: pointer; background: #007acc; color: white; border: none; border-radius: 5px; }
            button:hover { background: #005a9e; }
            .status { padding: 10px; background: #333; border-radius: 5px; margin: 10px 0; }
            .video-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
            video { width: 100%; background: #000; border-radius: 5px; }
            .clips { margin-top: 20px; background: #333; padding: 15px; border-radius: 5px; }
            @media (max-width: 768px) {
                .video-grid { grid-template-columns: 1fr; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 Bantai Pi Server - Dual CSI Cameras</h1>
            <div class="status" id="status">Status: Disconnected</div>
            <div class="controls">
                <button onclick="startCameras()">📹 Start Cameras</button>
                <button onclick="startRolling()">🎯 Start Rolling (Record)</button>
                <button onclick="stopRolling()">⏹️ Stop Rolling</button>
                <button onclick="startStreaming()">📡 Start WebRTC Streaming</button>
                <button onclick="getStatus()">📊 Get Status</button>
                <button onclick="listClips()">📁 List Clips</button>
            </div>
            <div class="video-grid">
                <div>
                    <h3>Camera 0 (cam0)</h3>
                    <img id="img0" src="" style="width:100%; background:#000;" alt="Camera 0">
                </div>
                <div>
                    <h3>Camera 1 (cam1)</h3>
                    <img id="img1" src="" style="width:100%; background:#000;" alt="Camera 1">
                </div>
            </div>
            <div class="clips" id="clips">Clips will appear here...</div>
        </div>
        <script>
            let ws = null;
            const statusDiv = document.getElementById('status');
            const clipsDiv = document.getElementById('clips');
            
            function connect() {
                ws = new WebSocket(`ws://${location.host}/ws/control`);
                ws.onopen = () => {
                    statusDiv.textContent = 'Status: Connected';
                };
                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    console.log('Message:', data);
                    statusDiv.textContent = `Status: ${data.type}`;
                };
                ws.onclose = () => {
                    setTimeout(connect, 2000);
                };
            }
            
            function startCameras() { if (ws) ws.send(JSON.stringify({command: 'start_cameras'})); }
            function startRolling() { if (ws) ws.send(JSON.stringify({command: 'start_rolling'})); }
            function stopRolling() { if (ws) ws.send(JSON.stringify({command: 'stop_rolling'})); }
            function startStreaming() { if (ws) ws.send(JSON.stringify({command: 'start_streaming'})); }
            function getStatus() { if (ws) ws.send(JSON.stringify({command: 'get_status'})); }
            function listClips() { 
                fetch('/api/clips').then(r=>r.json()).then(d=>{
                    clipsDiv.innerHTML = '<h3>Recorded Clips</h3>' + 
                        d.clips.map(c=>'<div>📄 '+c+'</div>').join('');
                });
            }
            
            // Start MJPEG streams
            setTimeout(()=>{
                document.getElementById('img0').src = '/stream/mjpeg/0?' + Date.now();
                document.getElementById('img1').src = '/stream/mjpeg/1?' + Date.now();
            }, 1000);
            
            connect();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@router.websocket("/ws/control")
async def websocket_control(websocket: WebSocket):
    await manager.connect(websocket)
    manager.control_clients.append(websocket)
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to Bantai Pi Server (Dual Camera)",
            "cameras": [0, 1]
        })
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                command = message.get("command")
                logger.info(f"Received command: {command}")
                
                if command == "start_cameras":
                    camera_manager.start_all([0, 1])
                    recorder_manager.setup_recorders(camera_manager)
                    await websocket.send_json({
                        "type": "cameras_started",
                        "message": "Both CSI cameras started",
                        "cameras": list(camera_manager.get_all_pipelines().keys()),
                        "timestamp": time.time()
                    })
                    await manager.broadcast_to_controls({"type": "event", "event": "cameras_started"})
                
                elif command == "start_rolling":
                    if not camera_manager.running:
                        camera_manager.start_all([0, 1])
                        recorder_manager.setup_recorders(camera_manager)
                    recorder_manager.start_rolling_all()
                    await websocket.send_json({
                        "type": "rolling_started",
                        "message": "Rolling recording started for both cameras (separate H.264 clips)",
                        "cameras": list(recorder_manager.recorders.keys()),
                        "timestamp": time.time()
                    })
                    await manager.broadcast_to_controls({"type": "event", "event": "rolling_started"})
                
                elif command == "stop_rolling":
                    recorder_manager.stop_rolling_all()
                    await websocket.send_json({
                        "type": "rolling_stopped",
                        "message": "Rolling recording stopped for both cameras",
                        "timestamp": time.time()
                    })
                    await manager.broadcast_to_controls({"type": "event", "event": "rolling_stopped"})
                
                elif command == "start_streaming":
                    if not camera_manager.running:
                        camera_manager.start_all([0, 1])
                    await websocket.send_json({
                        "type": "streaming_ready",
                        "message": "WebRTC streaming ready - use /offer endpoint with both camera tracks",
                        "turn_server": "cloudflare",
                        "cameras": list(camera_manager.get_all_pipelines().keys()),
                        "tracks": "H.264 encoded from both pipelines",
                        "timestamp": time.time()
                    })
                    await manager.broadcast_to_controls({"type": "event", "event": "streaming_ready"})
                
                elif command == "get_status":
                    await websocket.send_json({
                        "type": "status",
                        "cameras_running": camera_manager.running,
                        "rolling_active": recorder_manager.rolling_active,
                        "camera_count": len(camera_manager.get_all_pipelines()),
                        "recorders": list(recorder_manager.recorders.keys()),
                        "clips_dir": CLIPS_DIR,
                        "timestamp": time.time()
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown command: {command}"
                    })
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
            except Exception as e:
                logger.error(f"Error processing command: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})
    except WebSocketDisconnect:
        await manager.disconnect(websocket)

@router.post("/offer")
async def offer(request: Request):
    body = await request.json()
    offer_sdp = body.get("sdp")
    offer_type = body.get("type")
    
    if not offer_sdp or not offer_type:
        raise HTTPException(status_code=400, detail="Missing sdp or type")
    
    if not camera_manager.running:
        camera_manager.start_all([0, 1])
    if not camera_manager.get_all_pipelines():
        raise HTTPException(status_code=503, detail="No camera pipelines are available")
    
    try:
        return await webrtc_manager.create_peer_connection(offer_sdp, offer_type, camera_manager)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

@router.get("/stream/mjpeg/{camera_id}")
async def mjpeg_stream(camera_id: int):
    def generate():
        if camera_id not in [0, 1]:
            return
        if not camera_manager.running:
            camera_manager.start_all([0, 1])
        pipeline = camera_manager.get_pipeline(f"cam{camera_id}")
        if not pipeline:
            return
        while True:
            frame = pipeline.get_frame()
            if frame is not None:
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            import time
            time.sleep(0.066)
    
    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")

@router.get("/api/status")
async def api_status():
    return {
        "server": "running",
        "cameras_running": camera_manager.running,
        "rolling_active": recorder_manager.rolling_active,
        "pipelines": list(camera_manager.get_all_pipelines().keys()),
        "recorders": list(recorder_manager.recorders.keys()),
        "clips_dir": CLIPS_DIR,
        "timestamp": time.time()
    }

@router.get("/api/clips")
async def list_clips():
    try:
        clips = []
        if os.path.exists(CLIPS_DIR):
            for f in sorted(os.listdir(CLIPS_DIR), reverse=True):
                if f.endswith(('.mp4', '.avi', '.h264')):
                    clips.append(f)
        return {"clips": clips, "count": len(clips)}
    except Exception as e:
        return {"clips": [], "error": str(e)}

@router.get("/health")
async def health():
    return {
        "status": "healthy",
        "dual_cameras": True,
        "pipelines": len(camera_manager.get_all_pipelines()),
        "recorders": len(recorder_manager.recorders),
        "rolling": recorder_manager.rolling_active
    }

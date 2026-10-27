from fastapi import APIRouter, HTTPException
from aiortc import RTCPeerConnection, RTCSessionDescription
import logging
import os

from services.camera_service import CameraStreamTrack
from core.config import settings

logger = logging.getLogger("bantai-server")

router = APIRouter()
pcs = set()

@router.post("/offer")
async def offer(request: dict):
    try:
        offer = RTCSessionDescription(sdp=request["sdp"], type=request["type"])
        
        pc = RTCPeerConnection()
        pcs.add(pc)
        
        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"WebRTC connection state: {pc.connectionState}")
            if pc.connectionState in ["failed", "closed"]:
                await pc.close()
                pcs.discard(pc)
        
        # Add tracks for both CSI cameras
        cameras_to_stream = 0
        for i in range(2):  # Always try both CSI camera slots
            try:
                video_track = CameraStreamTrack(camera_index=i)
                pc.addTrack(video_track)
                cameras_to_stream += 1
                logger.info(f"Added WebRTC track for camera {i}")
            except Exception as e:
                logger.error(f"Failed to add camera {i} to WebRTC: {e}")
        
        if cameras_to_stream == 0:
            raise HTTPException(status_code=500, detail="No cameras available for streaming")
        
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
    except Exception as e:
        logger.error(f"WebRTC offer error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/webrtc/status")
async def webrtc_status():
    return {
        "active_connections": len(pcs),
        "turn_configured": bool(settings.TURN_SERVER),
        "cameras": [f"/dev/video{i}" for i in range(2)]
    }

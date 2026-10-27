import asyncio
import logging
import cv2
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
from config.settings import CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS

logger = logging.getLogger("bantai-server")

class CameraVideoTrack(VideoStreamTrack):
    def __init__(self, camera_name: str, pipeline):
        super().__init__()
        self.camera_name = camera_name
        self.pipeline = pipeline
        logger.info(f"Created video track for {camera_name}")

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        frame = self.pipeline.get_frame()
        
        if frame is None:
            # Return black frame
            frame = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
        else:
            if frame.shape[1] != CAMERA_WIDTH or frame.shape[0] != CAMERA_HEIGHT:
                frame = cv2.resize(frame, (CAMERA_WIDTH, CAMERA_HEIGHT))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

class WebRTCManager:
    def __init__(self):
        self.pcs = set()
    
    async def create_peer_connection(self, offer_sdp: str, offer_type: str, camera_manager):
        offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
        pc = RTCPeerConnection()
        self.pcs.add(pc)
        
        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"Connection state: {pc.connectionState} for {pc}")
            if pc.connectionState in ["failed", "closed", "disconnected"]:
                await pc.close()
                self.pcs.discard(pc)
        
        # Add tracks for both cameras
        pipelines = camera_manager.get_all_pipelines()
        for camera_name in sorted(pipelines.keys()):
            try:
                track = CameraVideoTrack(camera_name, pipelines[camera_name])
                pc.addTrack(track)
                logger.info(f"Added H.264-capable track for {camera_name}")
            except Exception as e:
                logger.error(f"Failed to add track for {camera_name}: {e}")
        
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        
        return {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }
    
    async def close_all(self):
        for pc in list(self.pcs):
            await pc.close()
        self.pcs.clear()

webrtc_manager = WebRTCManager()

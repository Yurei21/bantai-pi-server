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
    MAX_PEER_CONNECTIONS = 2

    def __init__(self):
        self.pcs = set()
        self._lock = asyncio.Lock()
    
    async def create_peer_connection(self, offer_sdp: str, offer_type: str, camera_manager):
        pipelines = camera_manager.get_all_pipelines()
        if not pipelines:
            raise RuntimeError("No camera pipelines are running")

        async with self._lock:
            if len(self.pcs) >= self.MAX_PEER_CONNECTIONS:
                raise RuntimeError("Maximum number of streaming connections reached")
            pc = RTCPeerConnection()
            self.pcs.add(pc)
        
        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"Connection state: {pc.connectionState} for {pc}")
            if pc.connectionState in ["failed", "closed"]:
                await self._close_peer_connection(pc)
        
        try:
            for camera_name in sorted(pipelines.keys()):
                track = CameraVideoTrack(camera_name, pipelines[camera_name])
                pc.addTrack(track)
                logger.info(f"Added shared pipeline track for {camera_name}")
        
            offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
            await pc.setRemoteDescription(offer)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
        
            return {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            }
        except Exception:
            await self._close_peer_connection(pc)
            raise

    async def _close_peer_connection(self, pc):
        if pc not in self.pcs:
            return
        self.pcs.discard(pc)
        await pc.close()
    
    async def close_all(self):
        await asyncio.gather(*(self._close_peer_connection(pc) for pc in list(self.pcs)))

webrtc_manager = WebRTCManager()

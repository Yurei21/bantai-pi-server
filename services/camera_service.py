import cv2
import logging
import os
from typing import Optional
import numpy as np

from aiortc import VideoStreamTrack
from av import VideoFrame

from core.config import settings

logger = logging.getLogger("bantai-server")

class CameraService:
    def __init__(self):
        self.cameras = {}
        self.streaming = False
        
    def get_available_cameras(self):
        available = []
        for i, device in enumerate(settings.CAMERA_DEVICES):
            if os.path.exists(device):
                available.append({"index": i, "device": device, "type": "csi"})
        # Also check for additional video devices
        for i in range(4):
            device = f"/dev/video{i}"
            if os.path.exists(device) and device not in [c["device"] for c in available]:
                available.append({"index": i, "device": device, "type": "usb"})
        return available
    
    def is_csi_camera(self, device_path):
        return device_path in settings.CAMERA_DEVICES or "csi" in device_path.lower()

camera_service = CameraService()

class CameraStreamTrack(VideoStreamTrack):
    def __init__(self, camera_index=0):
        super().__init__()
        self.camera_index = camera_index
        self.cap = None
        self._start()

    def _start(self):
        try:
            # Try to open camera
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                # Try with different backend for CSI
                self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
            
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.CAMERA_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.CAMERA_HEIGHT)
            self.cap.set(cv2.CAP_PROP_FPS, settings.CAMERA_FPS)
            logger.info(f"Started CSI/Camera {self.camera_index}")
        except Exception as e:
            logger.error(f"Failed to start camera {self.camera_index}: {e}")

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        if self.cap is None or not self.cap.isOpened():
            frame = np.zeros((settings.CAMERA_HEIGHT, settings.CAMERA_WIDTH, 3), dtype=np.uint8)
        else:
            ret, frame = self.cap.read()
            if not ret:
                frame = np.zeros((settings.CAMERA_HEIGHT, settings.CAMERA_WIDTH, 3), dtype=np.uint8)
            else:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

    def __del__(self):
        if self.cap is not None:
            self.cap.release()

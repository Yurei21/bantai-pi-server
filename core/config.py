import os
from typing import List

class Settings:
    def __init__(self):
        self.APP_NAME = "Bantai Pi Server"
        self.VERSION = "1.0.0"
        self.HOST = "0.0.0.0"
        self.PORT = 8000
        
        # Camera configuration for CSI cameras
        self.CAMERA_DEVICES = ["/dev/video0", "/dev/video1"]
        self.CSI_CAMERAS = True
        
        # WebRTC/Cloudflare TURN configuration
        self.TURN_SERVER = os.getenv("TURN_SERVER", "")
        self.TURN_USERNAME = os.getenv("TURN_USERNAME", "")
        self.TURN_CREDENTIAL = os.getenv("TURN_CREDENTIAL", "")
        
        # Camera streaming settings
        self.CAMERA_WIDTH = 1280
        self.CAMERA_HEIGHT = 720
        self.CAMERA_FPS = 30
        self.MJPEG_QUALITY = 70
        self.MJPEG_FPS = 15

settings = Settings()

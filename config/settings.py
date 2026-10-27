import os

# Server settings
HOST = os.getenv("BANTAI_HOST", "0.0.0.0")
PORT = int(os.getenv("BANTAI_PORT", "8000"))

# Camera settings
CAMERA_DEVICES = [0, 1]  # /dev/video0, /dev/video1 for CSI cameras
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30
MJPEG_FPS = 15
MJPEG_QUALITY = 70

# Recording settings
CLIPS_DIR = os.getenv("BANTAI_CLIPS_DIR", "/home/bantai/bantai-server/clips")
RECORDING_FPS = 30
RECORDING_CODEC = "h264"
RECORD_SEGMENT_DURATION = 30  # seconds per clip
MAX_CLIPS = 100

# WebRTC/Streaming settings
ICE_SERVERS = [
    {"urls": ["stun:stun.l.google.com:19302"]},
    # Add Cloudflare TURN server config as needed
    # {"urls": ["turn:turn.cloudflare.com:3478"], "username": "...", "credential": "..."}
]

# CORS settings
ALLOWED_ORIGINS = ["*"]

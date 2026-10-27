#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/bantai/bantai-server')

import uvicorn
from app import app
from core.config import settings

if __name__ == "__main__":
    print(f"🚀 Starting {settings.APP_NAME} on {settings.HOST}:{settings.PORT}")
    print(f"📹 CSI Cameras: {settings.CAMERA_DEVICES}")
    print(f"📱 Flutter app can connect via: http://<PI_IP>:{settings.PORT}")
    print(f"🌐 Web interface: http://localhost:{settings.PORT}")
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, log_level="info")

#!/usr/bin/env python3
import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from config.settings import HOST, PORT, ALLOWED_ORIGINS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("bantai-server")

app = FastAPI(
    title="Bantai Pi Server",
    description="Dual CSI Camera Server with WebRTC Streaming and Rolling Recording",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.on_event("startup")
async def startup_event():
    logger.info("Bantai Pi Server starting up...")
    logger.info("Dual CSI camera pipelines ready")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Bantai Pi Server...")
    from cameras.pipeline import camera_manager
    from recording.recorder import recorder_manager
    from streaming.webrtc import webrtc_manager
    recorder_manager.stop_all()
    camera_manager.stop_all()
    await webrtc_manager.close_all()

if __name__ == "__main__":
    logger.info(f"Starting server on {HOST}:{PORT}")
    uvicorn.run("app:app", host=HOST, port=PORT, log_level="info", reload=False)

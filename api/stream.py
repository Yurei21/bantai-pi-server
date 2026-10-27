from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import cv2
import asyncio

from core.config import settings

router = APIRouter()

async def generate_frames(camera_id: int):
    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        cap = cv2.VideoCapture(camera_id, cv2.CAP_V4L2)
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, settings.MJPEG_FPS)
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, settings.MJPEG_QUALITY])
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            await asyncio.sleep(1.0 / settings.MJPEG_FPS)
    finally:
        cap.release()

@router.get("/stream/camera/{camera_id}")
async def stream_camera(camera_id: int):
    return StreamingResponse(
        generate_frames(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

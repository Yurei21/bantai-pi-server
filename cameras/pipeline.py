import cv2
import logging
import threading
import time
from typing import Optional, Callable
import numpy as np

from config.settings import CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS

logger = logging.getLogger("bantai-server")

try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except Exception as e:
    logger.warning(f"picamera2 not available: {e}")
    PICAMERA2_AVAILABLE = False


class CameraPipeline:
    def __init__(self, camera_index: int, name: str = None):
        self.camera_index = camera_index
        self.name = name or f"cam{camera_index}"
        self.cap = None
        self.picam2 = None
        self.running = False
        self.lock = threading.Lock()
        self.latest_frame = None
        self.frame_callbacks = []
        self.thread = None
        self.use_picam2 = PICAMERA2_AVAILABLE

    def start(self):
        if self.running:
            return
        try:
            if self.use_picam2:
                # Discover available cameras from libcamera
                try:
                    cam_infos = Picamera2.global_camera_info()
                    logger.info(f"Detected cameras: {cam_infos}")
                except Exception as e:
                    logger.warning(f"Could not get global_camera_info: {e}")
                    cam_infos = []

                # Try in order of discovery first, fallback to camera_index
                cam_num = None
                if cam_infos and len(cam_infos) > self.camera_index:
                    # Use index in discovery order (most reliable on Pi 5 dual CSI)
                    cam_num = self.camera_index
                elif cam_infos and len(cam_infos) == 1 and self.camera_index == 1:
                    # Only 1 camera detected, don't try to open a second one
                    raise RuntimeError(f"Only {len(cam_infos)} camera detected by libcamera, cannot open {self.name}")
                else:
                    cam_num = self.camera_index

                logger.info(f"Opening {self.name} with Picamera2(camera_num={cam_num})")
                self.picam2 = Picamera2(camera_num=cam_num)
                config = self.picam2.create_preview_configuration(
                    main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "RGB888"},
                    controls={"FrameRate": CAMERA_FPS}
                )
                self.picam2.configure(config)
                self.picam2.start()
                logger.info(f"Started {self.name} via picamera2 (camera_num={cam_num})")
            else:
                self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
                if not self.cap.isOpened():
                    gst_str = f"v4l2src device=/dev/video{self.camera_index} io-mode=2 ! videoconvert ! video/x-raw,format=BGR,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! appsink drop=true sync=false"
                    self.cap = cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)
                if not self.cap.isOpened():
                    raise RuntimeError(f"Could not open camera {self.camera_index}")
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
                self.cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
                logger.info(f"Started {self.name} via OpenCV (index {self.camera_index})")

            self.running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()
        except Exception as e:
            logger.error(f"Failed to start {self.name}: {e}")
            raise

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        if self.picam2:
            try:
                self.picam2.stop()
                self.picam2.close()
            except Exception:
                pass
            self.picam2 = None
        if self.cap:
            self.cap.release()
            self.cap = None
        logger.info(f"Stopped {self.name}")

    def _capture_loop(self):
        while self.running:
            try:
                if self.use_picam2 and self.picam2 is not None:
                    frame = self.picam2.capture_array()
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                elif self.cap is not None and self.cap.isOpened():
                    ret, frame = self.cap.read()
                    if not ret:
                        time.sleep(0.01)
                        continue
                else:
                    time.sleep(0.01)
                    continue

                with self.lock:
                    self.latest_frame = frame.copy()

                for callback in self.frame_callbacks:
                    try:
                        callback(self.name, frame.copy())
                    except Exception as e:
                        logger.error(f"Callback error for {self.name}: {e}")

                time.sleep(1.0 / CAMERA_FPS)
            except Exception as e:
                logger.error(f"Capture loop error for {self.name}: {e}")
                time.sleep(0.1)

    def get_frame(self):
        with self.lock:
            if self.latest_frame is None:
                return None
            return self.latest_frame.copy()

    def add_frame_callback(self, callback: Callable):
        self.frame_callbacks.append(callback)

    def remove_frame_callback(self, callback: Callable):
        if callback in self.frame_callbacks:
            self.frame_callbacks.remove(callback)

    def is_running(self):
        if self.use_picam2:
            return self.running and self.picam2 is not None
        return self.running and self.cap is not None and self.cap.isOpened()


class DualCameraManager:
    def __init__(self):
        self.pipelines = {}
        self.running = False

    def start_all(self, camera_indices=[0, 1]):
        for idx in camera_indices:
            name = f"cam{idx}"
            if name in self.pipelines and self.pipelines[name].is_running():
                continue
            try:
                pipeline = CameraPipeline(idx, name)
                pipeline.start()
                self.pipelines[name] = pipeline
            except Exception as e:
                logger.error(f"Skipping {name}: {e}")
        self.running = len(self.pipelines) > 0
        logger.info(f"Started dual camera pipelines: {list(self.pipelines.keys())}")

    def stop_all(self):
        for pipeline in self.pipelines.values():
            pipeline.stop()
        self.pipelines.clear()
        self.running = False
        logger.info("Stopped all camera pipelines")

    def get_pipeline(self, name: str) -> Optional[CameraPipeline]:
        return self.pipelines.get(name)

    def get_all_pipelines(self):
        return self.pipelines

    def get_frame(self, name: str):
        pipeline = self.get_pipeline(name)
        if pipeline:
            return pipeline.get_frame()
        return None

    def add_callback_all(self, callback: Callable):
        for pipeline in self.pipelines.values():
            pipeline.add_frame_callback(callback)


camera_manager = DualCameraManager()
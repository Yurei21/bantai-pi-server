import cv2
import os
import logging
import time
import threading
from datetime import datetime
from pathlib import Path

from config.settings import CLIPS_DIR, RECORDING_FPS, CAMERA_WIDTH, CAMERA_HEIGHT

logger = logging.getLogger("bantai-server")

class RollingRecorder:
    def __init__(self, camera_name: str, pipeline):
        self.camera_name = camera_name
        self.pipeline = pipeline
        self.running = False
        self.recording = False
        self.writer = None
        self.current_filename = None
        self.thread = None
        self.start_time = None
        self.segment_duration = 30  # seconds per clip
        
        # Ensure clips directory exists
        os.makedirs(CLIPS_DIR, exist_ok=True)
    
    def start_rolling(self):
        if self.recording:
            return
        self.recording = True
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._record_loop, daemon=True)
            self.thread.start()
        logger.info(f"Started rolling recording for {self.camera_name}")
    
    def stop_rolling(self):
        self.recording = False
        if self.writer:
            self.writer.release()
            self.writer = None
        logger.info(f"Stopped rolling recording for {self.camera_name}")
    
    def stop_all(self):
        self.stop_rolling()
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
    
    def _create_writer(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.camera_name}_{timestamp}_h264.mp4"
        filepath = os.path.join(CLIPS_DIR, filename)
        self.current_filename = filepath
        
        # Try to use H.264 codec
        fourcc = cv2.VideoWriter_fourcc(*'avc1')  # H.264
        try:
            self.writer = cv2.VideoWriter(filepath, fourcc, RECORDING_FPS, (CAMERA_WIDTH, CAMERA_HEIGHT))
            if not self.writer.isOpened():
                # Fallback to mp4v if h264 not available
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                self.writer = cv2.VideoWriter(filepath.replace('_h264.mp4', '.mp4'), fourcc, RECORDING_FPS, (CAMERA_WIDTH, CAMERA_HEIGHT))
                self.current_filename = filepath.replace('_h264.mp4', '.mp4')
            logger.info(f"Recording {self.camera_name} to {self.current_filename}")
        except Exception as e:
            logger.error(f"Failed to create writer for {self.camera_name}: {e}")
            self.writer = None
    
    def _record_loop(self):
        self.start_time = time.time()
        self._create_writer()
        
        while self.running:
            if not self.recording:
                if self.writer:
                    self.writer.release()
                    self.writer = None
                time.sleep(0.1)
                continue
            
            # Check if need to start new segment
            if self.writer is None or (time.time() - self.start_time) >= self.segment_duration:
                if self.writer:
                    self.writer.release()
                self.start_time = time.time()
                self._create_writer()
            
            frame = self.pipeline.get_frame()
            if frame is not None and self.writer is not None:
                # Ensure frame is correct size
                if frame.shape[1] != CAMERA_WIDTH or frame.shape[0] != CAMERA_HEIGHT:
                    frame = cv2.resize(frame, (CAMERA_WIDTH, CAMERA_HEIGHT))
                self.writer.write(frame)
            else:
                time.sleep(0.01)
            
            time.sleep(1.0 / RECORDING_FPS)

class RollingRecorderManager:
    def __init__(self):
        self.recorders = {}
        self.rolling_active = False
    
    def setup_recorders(self, camera_manager):
        for name, pipeline in camera_manager.get_all_pipelines().items():
            if name not in self.recorders:
                self.recorders[name] = RollingRecorder(name, pipeline)
    
    def start_rolling_all(self):
        for recorder in self.recorders.values():
            recorder.start_rolling()
        self.rolling_active = True
        logger.info("Started rolling for all cameras")
    
    def stop_rolling_all(self):
        for recorder in self.recorders.values():
            recorder.stop_rolling()
        self.rolling_active = False
        logger.info("Stopped rolling for all cameras")
    
    def stop_all(self):
        for recorder in self.recorders.values():
            recorder.stop_all()
        self.recorders.clear()
        self.rolling_active = False

recorder_manager = RollingRecorderManager()

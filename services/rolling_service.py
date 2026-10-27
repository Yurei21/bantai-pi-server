import logging
import time
from typing import Optional

logger = logging.getLogger("bantai-server")

class RollingService:
    def __init__(self):
        self.rolling = False
        self.start_time = None
        self.last_command_time = None
        
    def start_rolling(self):
        if self.rolling:
            logger.warning("Rolling already in progress")
            return False
        
        self.rolling = True
        self.start_time = time.time()
        self.last_command_time = time.time()
        logger.info("Rolling mechanism started")
        # Here you would control GPIO/motor for rolling mechanism
        return True
    
    def stop_rolling(self):
        if not self.rolling:
            logger.warning("Rolling not in progress")
            return False
        
        self.rolling = False
        duration = time.time() - self.start_time if self.start_time else 0
        self.start_time = None
        self.last_command_time = time.time()
        logger.info(f"Rolling mechanism stopped. Duration: {duration:.2f}s")
        # Here you would stop GPIO/motor
        return True
    
    def get_status(self):
        status = {
            "rolling": self.rolling,
            "last_command_time": self.last_command_time
        }
        if self.rolling and self.start_time:
            status["duration"] = time.time() - self.start_time
        return status

rolling_service = RollingService()

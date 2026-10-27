import logging
from typing import List
from fastapi import WebSocket

logger = logging.getLogger("bantai-server")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.control_clients: List[WebSocket] = []
        self.streaming_clients: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.control_clients:
            self.control_clients.remove(websocket)
        if websocket in self.streaming_clients:
            self.streaming_clients.remove(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                pass

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception:
            pass

    async def broadcast_to_controls(self, message: dict):
        for connection in list(self.control_clients):
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

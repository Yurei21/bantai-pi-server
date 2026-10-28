import asyncio
import logging
import os
from typing import Any

import httpx
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

from streaming.webrtc import CameraVideoTrack

logger = logging.getLogger("bantai-server")


class CloudflareSFUPublisher:
    """Publish the Pi's shared camera pipelines as named SFU tracks."""

    def __init__(self):
        self.app_id = os.getenv("CF_SFU_APP_ID", "").strip()
        self.app_secret = os.getenv("CF_SFU_APP_SECRET", "").strip()
        self.pc: RTCPeerConnection | None = None
        self.session_id: str | None = None
        self._lock = asyncio.Lock()
        self._http: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=f"https://rtc.live.cloudflare.com/v1/apps/{self.app_id}",
                headers={"Authorization": f"Bearer {self.app_secret}"},
                timeout=30,
            )
        response = await self._http.request(method, path, **kwargs)
        response.raise_for_status()
        data = response.json()
        if data.get("errorCode"):
            raise RuntimeError(data.get("errorDescription", data["errorCode"]))
        return data

    async def start(self, camera_manager) -> dict:
        async with self._lock:
            if not self.configured:
                raise RuntimeError("Cloudflare SFU credentials are not configured")
            if self.pc and self.pc.connectionState not in ("failed", "closed"):
                return {"session_id": self.session_id, "tracks": ["cam0", "cam1"]}

            pipelines = camera_manager.get_all_pipelines()
            if not all(name in pipelines for name in ("cam0", "cam1")):
                raise RuntimeError("Both camera pipelines must be running")

            pc = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(urls=["stun:stun.cloudflare.com:3478"])]))
            session_id = None
            try:
                tracks = {}
                for camera_name in ("cam0", "cam1"):
                    track = CameraVideoTrack(camera_name, pipelines[camera_name])
                    transceiver = pc.addTransceiver(track, direction="sendonly")
                    tracks[camera_name] = transceiver

                offer = await pc.createOffer()
                await pc.setLocalDescription(offer)
                await self._wait_for_ice(pc)

                session = await self._request("POST", "/sessions/new")
                session_id = session["sessionId"]
                published = await self._request(
                    "POST", f"/sessions/{session_id}/tracks/new",
                    json={
                        "sessionDescription": {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp},
                        "tracks": [
                            {"location": "local", "mid": transceiver.mid, "trackName": name}
                            for name, transceiver in tracks.items()
                        ],
                    },
                )
                description = published.get("sessionDescription")
                if not description:
                    raise RuntimeError("Cloudflare SFU response omitted session description")
                results = published.get("tracks", [])
                errors = [item for item in results if item.get("errorCode")]
                if errors:
                    raise RuntimeError("SFU track publish failed: " + "; ".join(item.get("errorDescription", item["errorCode"]) for item in errors))
                await pc.setRemoteDescription(RTCSessionDescription(**description))
                await self._wait_for_connection(pc)
                self.pc = pc
                self.session_id = session_id
                return {"session_id": session_id, "tracks": list(tracks)}
            except Exception:
                await pc.close()
                if session_id:
                    try:
                        await self._close_session(session_id)
                    except Exception:
                        logger.warning("Could not clean up failed SFU session %s", session_id)
                raise

    @staticmethod
    async def _wait_for_connection(pc: RTCPeerConnection, timeout: float = 30) -> None:
        if pc.connectionState == "connected":
            return
        event = asyncio.Event()
        @pc.on("connectionstatechange")
        async def on_connection_state_change():
            if pc.connectionState == "connected":
                event.set()
            elif pc.connectionState in ("failed", "closed"):
                event.set()
        await asyncio.wait_for(event.wait(), timeout)
        if pc.connectionState != "connected":
            raise RuntimeError(f"SFU publisher connection ended in state {pc.connectionState}")

    @staticmethod
    async def _wait_for_ice(pc: RTCPeerConnection, timeout: float = 20) -> None:
        if pc.iceGatheringState == "complete":
            return
        event = asyncio.Event()
        @pc.on("icegatheringstatechange")
        async def on_ice_gathering_state_change():
            if pc.iceGatheringState == "complete":
                event.set()
        await asyncio.wait_for(event.wait(), timeout)

    async def _close_session(self, session_id: str) -> None:
        state = await self._request("GET", f"/sessions/{session_id}")
        mids = [track["mid"] for track in state.get("tracks", []) if track.get("mid") is not None and track.get("status") != "inactive"]
        if mids:
            await self._request(
                "PUT", f"/sessions/{session_id}/tracks/close",
                json={"tracks": [{"mid": mid} for mid in mids], "force": True},
            )

    async def stop(self) -> None:
        async with self._lock:
            pc, session_id = self.pc, self.session_id
            self.pc = None
            self.session_id = None
            if pc:
                await pc.close()
            if session_id and self.configured:
                try:
                    await self._close_session(session_id)
                except Exception:
                    logger.exception("Failed to close Cloudflare SFU session")
            if self._http:
                await self._http.aclose()
                self._http = None


sfu_publisher = CloudflareSFUPublisher()

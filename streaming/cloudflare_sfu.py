import asyncio
import logging
import os
from typing import Any

import httpx
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.rtcicetransport import connection_kwargs

from streaming.webrtc import CameraVideoTrack

logger = logging.getLogger("bantai-server")


class CloudflareSFUPublisher:
    """Publish the Pi's shared camera pipelines as named SFU tracks."""

    def __init__(self):
        self.app_id = os.getenv("CF_SFU_APP_ID", "").strip()
        self.app_secret = os.getenv("CF_SFU_APP_SECRET", "").strip()
        self.turn_urls = [url.strip() for url in os.getenv("CF_SFU_TURN_URLS", "").split(",") if url.strip()]
        self.turn_username = os.getenv("CF_SFU_TURN_USERNAME", "").strip()
        self.turn_credential = os.getenv("CF_SFU_TURN_CREDENTIAL", "").strip()
        self.ice_debug = os.getenv("CF_SFU_ICE_DEBUG", "").strip().lower() in {"1", "true", "yes"}
        if self.ice_debug:
            logging.getLogger("aioice").setLevel(logging.DEBUG)
            logging.getLogger("aioice.ice").setLevel(logging.DEBUG)
            logging.getLogger("aioice.turn").setLevel(logging.DEBUG)
            logger.info("SFU publisher detailed ICE diagnostics enabled")
        logger.info(
            "SFU environment check: turn_urls=%d username_set=%s credential_set=%s",
            len(self.turn_urls), bool(self.turn_username), bool(self.turn_credential),
        )
        self.pc: RTCPeerConnection | None = None
        self.session_id: str | None = None
        self._connection_task: asyncio.Task | None = None
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

            ice_servers = [RTCIceServer(urls=["stun:stun.cloudflare.com:3478"])]
            if self.turn_urls:
                if not self.turn_username or not self.turn_credential:
                    raise RuntimeError("CF_SFU_TURN_USERNAME and CF_SFU_TURN_CREDENTIAL are required when CF_SFU_TURN_URLS is set")
                ice_servers.append(RTCIceServer(
                    urls=self.turn_urls,
                    username=self.turn_username,
                    credential=self.turn_credential,
                ))
                logger.info("SFU publisher configured with TURN relay (%d URL(s))", len(self.turn_urls))
            else:
                logger.warning("SFU publisher has no TURN server configured; using STUN only")
            turn_options = connection_kwargs(ice_servers)
            if "turn_server" in turn_options:
                logger.info(
                    "SFU publisher TURN transport configured: server=%s:%s transport=%s tls=%s",
                    turn_options["turn_server"][0],
                    turn_options["turn_server"][1],
                    turn_options["turn_transport"],
                    turn_options["turn_ssl"],
                )
            pc = RTCPeerConnection(RTCConfiguration(iceServers=ice_servers))
            self._log_peer_connection(pc, "publisher")
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
                self._log_sdp_candidate_summary(pc.localDescription.sdp, "publisher local offer")

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
                self._log_sdp_candidate_summary(description.get("sdp", ""), "publisher Cloudflare answer")
                await pc.setRemoteDescription(RTCSessionDescription(**description))
                self.pc = pc
                self.session_id = session_id
                logger.info("SFU publisher negotiation submitted; waiting for ICE connection")
                await self._wait_for_connection(pc, timeout=60)
                if pc.connectionState != "connected":
                    raise RuntimeError(
                        f"SFU publisher failed to connect (ICE={pc.iceConnectionState}, peer={pc.connectionState})"
                    )
                logger.info("SFU publisher connected; tracks ready for subscription")
                self._connection_task = asyncio.create_task(
                    self._monitor_connection(pc, session_id),
                    name=f"sfu-publisher-{session_id[:8]}",
                )
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
    def _candidate_counts(sdp: str) -> str:
        counts = {}
        for line in sdp.splitlines():
            if not line.startswith("a=candidate:"):
                continue
            fields = line[2:].split()
            if len(fields) >= 8 and fields[6].lower() == "typ":
                candidate_type = fields[7].lower()
                transport = fields[2].lower()
                key = (candidate_type, transport)
                counts[key] = counts.get(key, 0) + 1
        return ", ".join(
            f"{candidate_type}/{transport}={count}"
            for (candidate_type, transport), count in sorted(counts.items())
        ) or "none"

    @staticmethod
    def _log_sdp_candidate_summary(sdp: str, label: str) -> None:
        logger.info("SFU %s ICE candidates: %s", label, CloudflareSFUPublisher._candidate_counts(sdp))
        media_sections = []
        current = None
        for line in sdp.splitlines():
            if line.startswith("m="):
                if current is not None:
                    media_sections.append(current)
                current = {"mid": None, "ice_ufrag": False, "ice_pwd": False, "candidates": 0, "end_of_candidates": False}
            elif current is not None:
                if line.startswith("a=mid:"):
                    current["mid"] = line[6:]
                elif line.startswith("a=ice-ufrag:"):
                    current["ice_ufrag"] = True
                elif line.startswith("a=ice-pwd:"):
                    current["ice_pwd"] = True
                elif line.startswith("a=candidate:"):
                    current["candidates"] += 1
                elif line == "a=end-of-candidates":
                    current["end_of_candidates"] = True
        if current is not None:
            media_sections.append(current)
        logger.info("SFU %s SDP ICE structure (values omitted): %s", label, media_sections or "no media sections")

    @staticmethod
    def _log_peer_connection(pc: RTCPeerConnection, label: str) -> None:
        @pc.on("icegatheringstatechange")
        async def on_ice_gathering_state_change():
            logger.info("SFU %s ICE gathering state: %s", label, pc.iceGatheringState)

        @pc.on("iceconnectionstatechange")
        async def on_ice_connection_state_change():
            logger.info("SFU %s ICE connection state: %s", label, pc.iceConnectionState)

        @pc.on("connectionstatechange")
        async def on_connection_state_change():
            logger.info("SFU %s peer connection state: %s", label, pc.connectionState)

    @staticmethod
    async def _wait_for_connection(pc: RTCPeerConnection, timeout: float) -> None:
        if pc.connectionState in ("connected", "failed", "closed"):
            return
        event = asyncio.Event()

        @pc.on("connectionstatechange")
        async def on_connection_state_change():
            if pc.connectionState in ("connected", "failed", "closed"):
                event.set()

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(
                "SFU publisher ICE timed out (ICE=%s, peer=%s, local_candidates=%s)",
                pc.iceConnectionState,
                pc.connectionState,
                CloudflareSFUPublisher._candidate_counts(
                    pc.localDescription.sdp if pc.localDescription else ""
                ),
            )
            raise

    async def _monitor_connection(self, pc: RTCPeerConnection, session_id: str) -> None:
        logger.info("SFU publisher monitoring connection (ICE=%s, peer=%s)", pc.iceConnectionState, pc.connectionState)
        if pc.connectionState == "connected":
            return
        event = asyncio.Event()

        @pc.on("connectionstatechange")
        async def on_connection_state_change():
            if pc.connectionState in ("connected", "failed", "closed"):
                event.set()

        try:
            await asyncio.wait_for(event.wait(), timeout=60)
        except asyncio.TimeoutError:
            logger.error("SFU publisher connection timed out (ICE=%s, peer=%s)", pc.iceConnectionState, pc.connectionState)
            await self._handle_connection_failure(pc, session_id)
            return
        if pc.connectionState == "connected":
            logger.info("SFU publisher connected")
        else:
            logger.error("SFU publisher connection ended (ICE=%s, peer=%s)", pc.iceConnectionState, pc.connectionState)
            await self._handle_connection_failure(pc, session_id)

    async def _handle_connection_failure(self, pc: RTCPeerConnection, session_id: str) -> None:
        async with self._lock:
            if self.pc is not pc:
                return
            self.pc = None
            self.session_id = None
            self._connection_task = None
            await pc.close()
            if self.configured:
                try:
                    await self._close_session(session_id)
                except Exception:
                    logger.warning("Could not clean up failed SFU session %s", session_id, exc_info=True)
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
            connection_task = self._connection_task
            self._connection_task = None
            if connection_task and connection_task is not asyncio.current_task():
                connection_task.cancel()
                await asyncio.gather(connection_task, return_exceptions=True)
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

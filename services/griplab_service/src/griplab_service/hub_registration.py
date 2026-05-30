"""Outbound hub registration for local griplab client processes."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from aiohttp import ClientSession, ClientWebSocketResponse

from griplab_service.config import ServiceConfig
from griplab_service.probe import build_probe
from griplab_service.protocol import ProtocolEnvelope, envelope_from_json, envelope_to_json


class HubRegistrationClient:
    """Maintains a client-to-hub websocket registration while the service runs."""

    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not self.config.hub.url or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._loop = None

    def _run_thread(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        finally:
            loop.close()

    async def _run(self) -> None:
        assert self.config.hub.url is not None
        while not self._stop.is_set():
            try:
                async with ClientSession() as session:
                    async with session.ws_connect(self.config.hub.url) as ws:
                        await self._hello(ws)
                        await self._heartbeat_loop(ws)
            except Exception:
                await asyncio.sleep(0.25)

    async def _hello(self, ws: ClientWebSocketResponse) -> None:
        payload = self._hello_payload()
        await ws.send_json(envelope_to_json(ProtocolEnvelope.request(
            message_id="hubreg-hello",
            method="peer.hello",
            payload=payload,
        )))
        msg = await ws.receive(timeout=5)
        if msg.type != 1:
            raise RuntimeError("hub hello failed")
        envelope = envelope_from_json(json.loads(msg.data))
        if envelope.kind != "response":
            raise RuntimeError("hub hello was rejected")

    async def _heartbeat_loop(self, ws: ClientWebSocketResponse) -> None:
        interval = self.config.hub.heartbeat_interval_ms / 1000
        seq = 0
        while not self._stop.is_set() and not ws.closed:
            seq += 1
            await ws.send_json(envelope_to_json(ProtocolEnvelope.request(
                message_id=f"hubreg-heartbeat-{seq:06d}",
                method="peer.heartbeat",
                payload={"peerId": self.config.self_peer_id, "ts": int(time.time() * 1000)},
            )))
            await asyncio.sleep(interval)

    def _hello_payload(self) -> dict[str, Any]:
        probe = build_probe(self.config)
        capabilities = dict(probe.get("capabilities", {}))
        workspace = dict(probe.get("workspace", {}))
        shells = capabilities.get("shells", [])
        return {
            "peerId": self.config.self_peer_id,
            "name": self.config.self_peer_id,
            "location": str(workspace.get("root", self.config.workspace.root)),
            "os": capabilities.get("os"),
            "shells": [str(shell) for shell in shells] if isinstance(shells, list) else [],
            "isSelf": False,
            "workspaceId": self.config.workspace.workspace_id,
        }

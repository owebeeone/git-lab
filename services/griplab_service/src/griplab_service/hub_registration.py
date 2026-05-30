"""Outbound hub registration for local griplab client processes."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType

from griplab_service.config import ServiceConfig
from griplab_service.probe import build_probe
from griplab_service.protocol import ErrorInfo, ProtocolEnvelope, envelope_from_json, envelope_to_json


class HubRegistrationClient:
    """Maintains a client-to-hub websocket registration while the service runs."""

    def __init__(self, config: ServiceConfig, *, local_ws_url: str | None = None) -> None:
        self.config = config
        self.local_ws_url = local_ws_url or self._config_local_ws_url()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._send_lock: asyncio.Lock | None = None
        self._active_ws: ClientWebSocketResponse | None = None

    def start(self) -> None:
        if not self.config.hub.url or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._loop is not None:
            active_ws = self._active_ws
            if active_ws is not None:
                asyncio.run_coroutine_threadsafe(active_ws.close(), self._loop)
            else:
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
                        self._active_ws = ws
                        self._send_lock = asyncio.Lock()
                        await self._hello(ws)
                        await self._hub_loop(session, ws)
            except Exception:
                await asyncio.sleep(0.25)
            finally:
                self._active_ws = None

    async def _hub_loop(self, session: ClientSession, ws: ClientWebSocketResponse) -> None:
        heartbeat = asyncio.create_task(self._heartbeat_loop(ws))
        proxy_tasks: set[asyncio.Task[None]] = set()
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                envelope = envelope_from_json(json.loads(msg.data))
                if envelope.kind != "request":
                    continue
                task = asyncio.create_task(self._proxy_hub_request(session, ws, envelope))
                proxy_tasks.add(task)
                task.add_done_callback(proxy_tasks.discard)
        finally:
            heartbeat.cancel()
            for task in list(proxy_tasks):
                task.cancel()
            await asyncio.gather(heartbeat, *proxy_tasks, return_exceptions=True)

    async def _hello(self, ws: ClientWebSocketResponse) -> None:
        payload = self._hello_payload()
        await self._send_to_hub(ws, ProtocolEnvelope.request(
            message_id="hubreg-hello",
            method="peer.hello",
            payload=payload,
        ))
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
            await self._send_to_hub(ws, ProtocolEnvelope.request(
                message_id=f"hubreg-heartbeat-{seq:06d}",
                method="peer.heartbeat",
                payload={"peerId": self.config.self_peer_id, "ts": int(time.time() * 1000)},
            ))
            await asyncio.sleep(interval)

    async def _proxy_hub_request(
        self,
        session: ClientSession,
        hub_ws: ClientWebSocketResponse,
        envelope: ProtocolEnvelope,
    ) -> None:
        try:
            async with session.ws_connect(self.local_ws_url) as local_ws:
                await local_ws.send_json(envelope_to_json(envelope))
                async for msg in local_ws:
                    if msg.type != WSMsgType.TEXT:
                        break
                    response = envelope_from_json(json.loads(msg.data))
                    await self._send_to_hub(hub_ws, response)
                    if response.kind in {"response", "error"} and not envelope.stream_id:
                        return
        except Exception as exc:
            await self._send_to_hub(hub_ws, ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("local-proxy-error", str(exc)),
            ))

    async def _send_to_hub(self, ws: ClientWebSocketResponse, envelope: ProtocolEnvelope) -> None:
        if self._send_lock is None:
            await ws.send_json(envelope_to_json(envelope))
            return
        async with self._send_lock:
            await ws.send_json(envelope_to_json(envelope))

    def _hello_payload(self) -> dict[str, Any]:
        probe = build_probe(self.config)
        capabilities = dict(probe.get("capabilities", {}))
        workspace = dict(probe.get("workspace", {}))
        shells = capabilities.get("shells", [])
        client_payload = self._client_payload_manifest()
        return {
            "peerId": self.config.self_peer_id,
            "name": self.config.self_peer_id,
            "location": str(workspace.get("root", self.config.workspace.root)),
            "os": capabilities.get("os"),
            "shells": [str(shell) for shell in shells] if isinstance(shells, list) else [],
            "isSelf": self.config.self_peer_id == "me",
            "workspaceId": self.config.workspace.workspace_id,
            "clientPayload": client_payload,
        }

    def _config_local_ws_url(self) -> str:
        host = self.config.listen.host
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        return f"ws://{host}:{self.config.listen.port}/ws"

    def _client_payload_manifest(self) -> dict[str, Any]:
        if self.config.path is None:
            return {}
        manifest = self.config.path.parent / "client_payload.json"
        if not manifest.exists():
            return {}
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(value) if isinstance(value, dict) else {}

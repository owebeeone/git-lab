"""aiohttp hub app for peer hello and presence streams."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import WSMsgType, web

from griplab_service.chat_store import ChatStore, chat_store_root
from griplab_service.config import ServiceConfig
from griplab_service.protocol import (
    ErrorInfo,
    ProtocolEnvelope,
    ProtocolValidationError,
    StreamEvent,
    envelope_from_json,
    envelope_to_json,
)

CONFIG_KEY = web.AppKey("config", ServiceConfig)
REGISTRY_KEY = web.AppKey("registry", Any)
CHAT_KEY = web.AppKey("chat", Any)


class HubServer:
    """Hub aiohttp server used for local integration tests and peer presence."""

    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._stopped = threading.Event()
        self._host = config.listen.host
        self._port = config.listen.port

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self._host}:{self._port}/ws"

    def start(self) -> None:
        if self._thread is not None:
            return
        self._started.clear()
        self._stopped.clear()
        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()
        if not self._started.wait(timeout=5):
            raise RuntimeError("hub server did not start")

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._loop = None
        self._runner = None
        self._site = None

    def serve_forever(self) -> None:
        self.start()
        try:
            self._stopped.wait()
        finally:
            self.stop()

    def _run_thread(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start_async())
            self._started.set()
            loop.run_forever()
        finally:
            loop.run_until_complete(self._cleanup_async())
            loop.close()
            self._stopped.set()

    async def _start_async(self) -> None:
        app = create_app(self.config)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.config.listen.host, self.config.listen.port)
        await self._site.start()
        sockets = getattr(self._site, "_server").sockets if self._site is not None else None
        if sockets:
            sock_host, sock_port = sockets[0].getsockname()[:2]
            self._host = str(sock_host)
            self._port = int(sock_port)

    async def _cleanup_async(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


def create_app(config: ServiceConfig) -> web.Application:
    app = web.Application()
    app[CONFIG_KEY] = config
    app[REGISTRY_KEY] = PeerRegistry()
    app[CHAT_KEY] = ChatStore(chat_store_root(config.path, config.workspace.root))
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ws", handle_ws)
    return app


async def handle_health(request: web.Request) -> web.Response:
    config = request.app[CONFIG_KEY]
    return web.json_response({"ok": True, "mode": config.mode})


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    connection = HubConnection(request.app[CONFIG_KEY], request.app[REGISTRY_KEY], request.app[CHAT_KEY], ws)
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                envelope = envelope_from_json(json.loads(msg.data))
                await handle_protocol_message(connection, envelope)
            except (json.JSONDecodeError, KeyError, ProtocolValidationError, ValueError) as exc:
                await connection.send(ProtocolEnvelope.error_response(
                    message_id="invalid",
                    method=None,
                    error=ErrorInfo("bad-message", str(exc)),
                ))
    finally:
        await connection.close()
    return ws


async def handle_protocol_message(connection: "HubConnection", envelope: ProtocolEnvelope) -> None:
    if envelope.kind != "request":
        await connection.send(ProtocolEnvelope.error_response(
            message_id=envelope.message_id,
            method=envelope.method,
            error=ErrorInfo("bad-kind", "only request envelopes are accepted by the hub"),
        ))
        return
    if envelope.method == "peer.hello":
        peer_id = connection.registry.hello(envelope.payload)
        connection.peer_id = peer_id
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"peerId": peer_id},
        ))
        connection.registry.publish()
        return
    if envelope.method == "peer.presence.subscribe":
        if not envelope.stream_id:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "peer.presence.subscribe requires streamId"),
            ))
            return
        await connection.subscribe_presence(envelope.message_id, envelope.stream_id)
        return
    if envelope.method == "chat.subscribe":
        if not envelope.stream_id:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "chat.subscribe requires streamId"),
            ))
            return
        await connection.subscribe_chat(envelope.message_id, envelope.stream_id)
        return
    if envelope.method == "chat.post":
        try:
            message = connection.chat_store.post(
                envelope.payload,
                default_sender_id=connection.peer_id or connection.config.self_peer_id,
            )
        except ValueError as exc:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("bad-chat-message", str(exc)),
            ))
            return
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"message": message},
        ))
        return
    await connection.send(ProtocolEnvelope.error_response(
        message_id=envelope.message_id,
        method=envelope.method,
        error=ErrorInfo("unknown-method", f"unknown method: {envelope.method}"),
    ))


@dataclass
class PresenceStream:
    message_id: str
    stream_id: str
    queue: asyncio.Queue[None]
    seq: int = 0
    task: asyncio.Task[None] | None = None


@dataclass
class ChatStream:
    message_id: str
    stream_id: str
    queue: asyncio.Queue[None]
    seq: int = 0
    task: asyncio.Task[None] | None = None


class HubConnection:
    def __init__(
        self,
        config: ServiceConfig,
        registry: "PeerRegistry",
        chat_store: ChatStore,
        ws: web.WebSocketResponse,
    ) -> None:
        self.config = config
        self.registry = registry
        self.chat_store = chat_store
        self.ws = ws
        self.peer_id: str | None = None
        self.presence_streams: dict[str, PresenceStream] = {}
        self.chat_streams: dict[str, ChatStream] = {}
        self._send_lock = asyncio.Lock()

    async def send(self, envelope: ProtocolEnvelope) -> None:
        async with self._send_lock:
            await self.ws.send_json(envelope_to_json(envelope))

    async def subscribe_presence(self, message_id: str, stream_id: str) -> None:
        queue = self.registry.add_presence_subscriber()
        stream = PresenceStream(message_id=message_id, stream_id=stream_id, queue=queue)
        self.presence_streams[stream_id] = stream
        await self._publish_presence(stream)
        stream.task = asyncio.create_task(self._watch_presence(stream))

    async def subscribe_chat(self, message_id: str, stream_id: str) -> None:
        queue: asyncio.Queue[None] = asyncio.Queue()
        self.chat_store.add_subscriber(queue)
        stream = ChatStream(message_id=message_id, stream_id=stream_id, queue=queue)
        self.chat_streams[stream_id] = stream
        await self._publish_chat(stream)
        stream.task = asyncio.create_task(self._watch_chat(stream))

    async def close(self) -> None:
        if self.peer_id:
            self.registry.mark_offline(self.peer_id)
        streams = list(self.presence_streams.values())
        self.presence_streams.clear()
        for stream in streams:
            self.registry.remove_presence_subscriber(stream.queue)
            if stream.task is not None:
                stream.task.cancel()
        for stream in streams:
            if stream.task is None:
                continue
            try:
                await stream.task
            except asyncio.CancelledError:
                pass
        chat_streams = list(self.chat_streams.values())
        self.chat_streams.clear()
        for stream in chat_streams:
            self.chat_store.remove_subscriber(stream.queue)
            if stream.task is not None:
                stream.task.cancel()
        for stream in chat_streams:
            if stream.task is None:
                continue
            try:
                await stream.task
            except asyncio.CancelledError:
                pass

    async def _watch_presence(self, stream: PresenceStream) -> None:
        try:
            while stream.stream_id in self.presence_streams:
                await stream.queue.get()
                await self._publish_presence(stream)
        except asyncio.CancelledError:
            raise

    async def _publish_presence(self, stream: PresenceStream) -> None:
        stream.seq += 1
        await self.send(ProtocolEnvelope.stream_event(
            message_id=stream.message_id,
            method="peer.presence.subscribe",
            stream_id=stream.stream_id,
            event=StreamEvent(
                stream_id=stream.stream_id,
                seq=stream.seq,
                event="snapshot",
                payload={"peers": self.registry.peers_json()},
            ),
        ))

    async def _watch_chat(self, stream: ChatStream) -> None:
        try:
            while stream.stream_id in self.chat_streams:
                await stream.queue.get()
                await self._publish_chat(stream)
        except asyncio.CancelledError:
            raise

    async def _publish_chat(self, stream: ChatStream) -> None:
        stream.seq += 1
        await self.send(ProtocolEnvelope.stream_event(
            message_id=stream.message_id,
            method="chat.subscribe",
            stream_id=stream.stream_id,
            event=StreamEvent(
                stream_id=stream.stream_id,
                seq=stream.seq,
                event="snapshot",
                payload={"messages": self.chat_store.messages()},
            ),
        ))


class PeerRegistry:
    def __init__(self) -> None:
        self.peers: dict[str, dict[str, object]] = {}
        self.presence_subscribers: set[asyncio.Queue[None]] = set()

    def hello(self, payload: dict[str, Any]) -> str:
        peer_id = str(payload.get("peerId", ""))
        if not peer_id:
            raise ValueError("peer.hello requires peerId")
        self.peers[peer_id] = {
            "id": peer_id,
            "name": str(payload.get("name", peer_id)),
            "sshAddress": str(payload.get("sshAddress", "")),
            "location": str(payload.get("location", "")),
            "os": payload.get("os"),
            "shells": list(payload.get("shells", [])),
            "online": True,
            "isSelf": bool(payload.get("isSelf", False)),
            "lastSeen": int(time.time() * 1000),
        }
        return peer_id

    def mark_offline(self, peer_id: str) -> None:
        peer = self.peers.get(peer_id)
        if peer is None:
            return
        peer["online"] = False
        peer["lastSeen"] = int(time.time() * 1000)
        self.publish()

    def peers_json(self) -> list[dict[str, object]]:
        return sorted(self.peers.values(), key=lambda item: str(item["id"]))

    def add_presence_subscriber(self) -> asyncio.Queue[None]:
        queue: asyncio.Queue[None] = asyncio.Queue()
        self.presence_subscribers.add(queue)
        return queue

    def remove_presence_subscriber(self, queue: asyncio.Queue[None]) -> None:
        self.presence_subscribers.discard(queue)

    def publish(self) -> None:
        for queue in list(self.presence_subscribers):
            queue.put_nowait(None)

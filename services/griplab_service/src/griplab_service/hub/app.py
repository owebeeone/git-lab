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
    if envelope.kind in {"response", "error", "stream-event"}:
        await connection.registry.handle_relay_message(connection, envelope)
        return
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
        connection.registry.register_connection(peer_id, connection)
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
    if envelope.method == "hub.route.request":
        await connection.registry.route_request(connection, envelope)
        return
    if envelope.method == "hub.route.subscribe":
        await connection.registry.route_subscribe(connection, envelope)
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


@dataclass
class RoutedRequest:
    caller: "HubConnection"
    caller_message_id: str
    caller_method: str
    target: "HubConnection"
    timeout_task: asyncio.Task[None] | None = None


@dataclass
class RoutedStream:
    caller: "HubConnection"
    caller_message_id: str
    caller_stream_id: str
    caller_method: str
    target: "HubConnection"
    target_stream_id: str


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
            await self.registry.connection_closed(self.peer_id, self)
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
    route_request_timeout_seconds = 5.0

    def __init__(self) -> None:
        self.peers: dict[str, dict[str, object]] = {}
        self.connections: dict[str, HubConnection] = {}
        self.presence_subscribers: set[asyncio.Queue[None]] = set()
        self._relay_index = 0
        self.routed_requests: dict[str, RoutedRequest] = {}
        self.routed_streams_by_target: dict[str, RoutedStream] = {}
        self.routed_streams_by_caller: dict[str, RoutedStream] = {}

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

    def register_connection(self, peer_id: str, connection: HubConnection) -> None:
        self.connections[peer_id] = connection

    async def connection_closed(self, peer_id: str, connection: HubConnection) -> None:
        if self.connections.get(peer_id) is connection:
            self.connections.pop(peer_id, None)
        await self._fail_target_routes(connection, "peer-offline", f"target peer disconnected: {peer_id}")
        self._remove_caller_routes(connection)
        self.mark_offline(peer_id)

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

    async def route_request(self, caller: HubConnection, envelope: ProtocolEnvelope) -> None:
        target = await self._resolve_target(caller, envelope)
        if target is None:
            return
        target_peer_id, target_connection, method, payload = target
        del target_peer_id
        target_message_id = self._next_relay_message_id()
        routed = RoutedRequest(
            caller=caller,
            caller_message_id=envelope.message_id,
            caller_method=envelope.method or "hub.route.request",
            target=target_connection,
        )
        routed.timeout_task = asyncio.create_task(self._expire_routed_request(target_message_id))
        self.routed_requests[target_message_id] = routed
        await target_connection.send(ProtocolEnvelope.request(
            message_id=target_message_id,
            method=method,
            payload=payload,
        ))

    async def route_subscribe(self, caller: HubConnection, envelope: ProtocolEnvelope) -> None:
        if not envelope.stream_id:
            await caller.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "hub.route.subscribe requires streamId"),
            ))
            return
        target = await self._resolve_target(caller, envelope)
        if target is None:
            return
        target_peer_id, target_connection, method, payload = target
        del target_peer_id
        target_message_id = self._next_relay_message_id()
        target_stream_id = self._next_relay_stream_id()
        stream = RoutedStream(
            caller=caller,
            caller_message_id=envelope.message_id,
            caller_stream_id=envelope.stream_id,
            caller_method=envelope.method or "hub.route.subscribe",
            target=target_connection,
            target_stream_id=target_stream_id,
        )
        self.routed_streams_by_target[target_stream_id] = stream
        self.routed_streams_by_caller[envelope.stream_id] = stream
        await target_connection.send(ProtocolEnvelope(
            message_id=target_message_id,
            kind="request",
            method=method,
            stream_id=target_stream_id,
            payload=payload,
        ))

    async def handle_relay_message(self, target: HubConnection, envelope: ProtocolEnvelope) -> None:
        if envelope.kind in {"response", "error"}:
            await self._handle_relay_response(target, envelope)
            return
        if envelope.kind == "stream-event":
            await self._handle_relay_stream_event(target, envelope)

    async def _handle_relay_response(self, target: HubConnection, envelope: ProtocolEnvelope) -> None:
        routed = self.routed_requests.pop(envelope.message_id, None)
        if routed is None:
            return
        if routed.target is not target:
            self.routed_requests[envelope.message_id] = routed
            return
        if routed.timeout_task is not None:
            routed.timeout_task.cancel()
        if envelope.kind == "error":
            await routed.caller.send(ProtocolEnvelope.error_response(
                message_id=routed.caller_message_id,
                method=routed.caller_method,
                error=envelope.error or ErrorInfo("target-error", "target returned an error"),
            ))
            return
        await routed.caller.send(ProtocolEnvelope.response(
            message_id=routed.caller_message_id,
            method=routed.caller_method,
            payload=envelope.payload,
        ))

    async def _handle_relay_stream_event(self, target: HubConnection, envelope: ProtocolEnvelope) -> None:
        if not envelope.stream_id:
            return
        routed = self.routed_streams_by_target.get(envelope.stream_id)
        if routed is None or routed.target is not target:
            return
        event = StreamEvent(
            stream_id=routed.caller_stream_id,
            seq=int(envelope.payload.get("seq", 0)),
            event=str(envelope.payload.get("event", "message")),
            payload=dict(envelope.payload.get("payload", {})),
        )
        await routed.caller.send(ProtocolEnvelope.stream_event(
            message_id=routed.caller_message_id,
            method=routed.caller_method,
            stream_id=routed.caller_stream_id,
            event=event,
        ))

    async def _resolve_target(
        self,
        caller: HubConnection,
        envelope: ProtocolEnvelope,
    ) -> tuple[str, HubConnection, str, dict[str, Any]] | None:
        target_peer_id = str(envelope.payload.get("targetPeerId", ""))
        method = str(envelope.payload.get("method", ""))
        payload_value = envelope.payload.get("payload", {})
        payload = dict(payload_value) if isinstance(payload_value, dict) else {}
        if not target_peer_id:
            await caller.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-target", "routed request requires targetPeerId"),
            ))
            return None
        if not method:
            await caller.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-method", "routed request requires method"),
            ))
            return None
        target_connection = self.connections.get(target_peer_id)
        if target_connection is None:
            await caller.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("peer-offline", f"target peer is not connected: {target_peer_id}"),
            ))
            return None
        return target_peer_id, target_connection, method, payload

    async def _fail_target_routes(self, target: HubConnection, code: str, message: str) -> None:
        for target_message_id, routed in list(self.routed_requests.items()):
            if routed.target is not target:
                continue
            self.routed_requests.pop(target_message_id, None)
            if routed.timeout_task is not None:
                routed.timeout_task.cancel()
            await routed.caller.send(ProtocolEnvelope.error_response(
                message_id=routed.caller_message_id,
                method=routed.caller_method,
                error=ErrorInfo(code, message),
            ))
        for target_stream_id, routed in list(self.routed_streams_by_target.items()):
            if routed.target is not target:
                continue
            self.routed_streams_by_target.pop(target_stream_id, None)
            self.routed_streams_by_caller.pop(routed.caller_stream_id, None)
            await routed.caller.send(ProtocolEnvelope.stream_event(
                message_id=routed.caller_message_id,
                method=routed.caller_method,
                stream_id=routed.caller_stream_id,
                event=StreamEvent(
                    stream_id=routed.caller_stream_id,
                    seq=0,
                    event="error",
                    payload={"code": code, "message": message},
                ),
            ))

    def _remove_caller_routes(self, caller: HubConnection) -> None:
        for target_stream_id, routed in list(self.routed_streams_by_target.items()):
            if routed.caller is not caller:
                continue
            self.routed_streams_by_target.pop(target_stream_id, None)
            self.routed_streams_by_caller.pop(routed.caller_stream_id, None)
        for target_message_id, routed in list(self.routed_requests.items()):
            if routed.caller is caller:
                self.routed_requests.pop(target_message_id, None)
                if routed.timeout_task is not None:
                    routed.timeout_task.cancel()

    def _next_relay_message_id(self) -> str:
        self._relay_index += 1
        return f"relay-m{self._relay_index:06d}"

    def _next_relay_stream_id(self) -> str:
        self._relay_index += 1
        return f"relay-s{self._relay_index:06d}"

    async def _expire_routed_request(self, target_message_id: str) -> None:
        try:
            await asyncio.sleep(self.route_request_timeout_seconds)
        except asyncio.CancelledError:
            raise
        routed = self.routed_requests.pop(target_message_id, None)
        if routed is None:
            return
        await routed.caller.send(ProtocolEnvelope.error_response(
            message_id=routed.caller_message_id,
            method=routed.caller_method,
            error=ErrorInfo("target-timeout", "target peer did not respond before timeout"),
        ))

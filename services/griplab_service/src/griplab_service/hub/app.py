"""aiohttp hub app for peer hello and presence streams."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientSession, WSMsgType, web
from diffstream import (
    DiffDiagnostic,
    DiffEndpoint,
    DiffPayload,
    DiffSourceState,
    DiffWindow,
    build_diff_payload,
    effective_window,
    endpoint_from_json,
    format_diff_id,
    format_diff_version,
    payload_to_json,
    window_from_json,
)
from filedelta import (
    TextWindowSnapshot,
    apply_text_window_delta,
    reset_from_json,
    text_window_delta_from_json,
    text_window_snapshot_from_json,
)

from griplab_service.chat_store import ChatStore, chat_store_root
from griplab_service.collaborators import (
    CollaboratorRecord,
    collaborators_path,
    configured_presence,
    connected_presence,
    health_for_presence,
    load_collaborators,
    mark_presence_offline,
    remove_collaborator,
    self_presence,
    upsert_collaborator,
)
from griplab_service.config import ServiceConfig
from griplab_service.protocol import (
    ErrorInfo,
    ProtocolEnvelope,
    ProtocolValidationError,
    StreamEvent,
    envelope_from_json,
    envelope_to_json,
)
from griplab_service.restart import schedule_process_restart
from griplab_service.ssh_bootstrap import HubBootstrapWorker

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
        app[REGISTRY_KEY].start_bootstrap(self._host, self._port)

    async def _cleanup_async(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


def create_app(config: ServiceConfig) -> web.Application:
    app = web.Application()
    app[CONFIG_KEY] = config
    app[REGISTRY_KEY] = PeerRegistry(config)
    app[CHAT_KEY] = ChatStore(chat_store_root(config.path, config.workspace.root))
    app.on_cleanup.append(cleanup_app)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ws", handle_ws)
    return app


async def cleanup_app(app: web.Application) -> None:
    await app[REGISTRY_KEY].close_bootstrap()


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
    if envelope.method == "peer.heartbeat":
        try:
            connection.registry.heartbeat(envelope.payload)
        except ValueError as exc:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("bad-request", str(exc)),
            ))
            return
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"ok": True},
        ))
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
    if envelope.method == "peer.health.get":
        try:
            payload = connection.registry.peer_health(envelope.payload)
        except ValueError as exc:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("bad-request", str(exc)),
            ))
            return
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload=payload,
        ))
        return
    if envelope.method == "peer.collaborator.list":
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"collaborators": connection.registry.collaborators_json()},
        ))
        return
    if envelope.method == "peer.collaborator.upsert":
        try:
            collaborator = connection.registry.upsert_collaborator(envelope.payload)
        except ValueError as exc:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("bad-collaborator", str(exc)),
            ))
            return
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"collaborator": collaborator},
        ))
        return
    if envelope.method == "peer.collaborator.remove":
        peer_id = str(envelope.payload.get("peerId", ""))
        if not peer_id:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("bad-collaborator", "peer.collaborator.remove requires peerId"),
            ))
            return
        removed = connection.registry.remove_collaborator(peer_id)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"removed": removed},
        ))
        return
    if envelope.method == "admin.restart":
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"restarting": True, "target": "hub"},
        ))
        schedule_process_restart()
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
    if envelope.method == "diff.subscribe":
        if not envelope.stream_id:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "diff.subscribe requires streamId"),
            ))
            return
        await connection.registry.open_diff_stream(connection, envelope.message_id, envelope.stream_id, envelope.payload)
        return
    if envelope.method == "diff.window.update":
        updated = await connection.registry.update_diff_window(connection, envelope.payload)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"updated": updated},
        ))
        return
    if envelope.method == "diff.unsubscribe":
        stream_id = str(envelope.payload.get("streamId", ""))
        stopped = await connection.registry.close_diff_stream(connection, stream_id)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"stopped": stopped},
        ))
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


@dataclass
class TunnelRoutedStream:
    caller: "HubConnection"
    caller_message_id: str
    caller_stream_id: str
    caller_method: str
    target_stream_id: str
    task: asyncio.Task[None] | None = None


@dataclass(frozen=True)
class PeerTunnel:
    peer_id: str
    local_peer_port: int
    remote_hub_port: int | None = None
    remote_client_port: int | None = None

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.local_peer_port}/ws"


@dataclass
class HubDiffStream:
    caller: "HubConnection"
    message_id: str
    stream_id: str
    diff_id: str
    left: DiffEndpoint
    right: DiffEndpoint
    window: DiffWindow
    context_lines: int
    left_target: "HubConnection | None" = None
    right_target: "HubConnection | None" = None
    left_target_stream_id: str | None = None
    right_target_stream_id: str | None = None
    left_snapshot: TextWindowSnapshot | None = None
    right_snapshot: TextWindowSnapshot | None = None
    seq: int = 0
    version: int = 0


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
        self.diff_streams: dict[str, HubDiffStream] = {}
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
        await self.registry.close_connection_diff_streams(self)

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

    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self.collaborators_path = collaborators_path(config)
        self.collaborators: dict[str, CollaboratorRecord] = self._load_collaborators()
        self.peers: dict[str, dict[str, object]] = {}
        self.self_peer = self_presence(config)
        self.connections: dict[str, HubConnection] = {}
        self.presence_subscribers: set[asyncio.Queue[None]] = set()
        self._relay_index = 0
        self.routed_requests: dict[str, RoutedRequest] = {}
        self.routed_streams_by_target: dict[str, RoutedStream] = {}
        self.routed_streams_by_caller: dict[str, RoutedStream] = {}
        self.tunnel_streams_by_caller: dict[str, TunnelRoutedStream] = {}
        self.diff_sources_by_target_stream: dict[str, tuple[HubDiffStream, str]] = {}
        self.tunnels: dict[str, PeerTunnel] = {}
        self.bootstrap_worker: HubBootstrapWorker | None = None
        self.bootstrap_tasks: dict[str, asyncio.Task[None]] = {}
        self.bootstrap_states: dict[str, dict[str, object]] = {}
        self.remote_hub_ports: dict[str, int] = {}
        self.remote_client_ports: dict[str, int] = {}
        self._next_remote_hub_port = 43140
        self._next_remote_client_port = 3141

    def hello(self, payload: dict[str, Any]) -> str:
        peer = connected_presence(payload)
        peer_id = str(peer["id"])
        self.peers[peer_id] = peer
        return peer_id

    def register_connection(self, peer_id: str, connection: HubConnection) -> None:
        self.connections[peer_id] = connection

    def register_tunnel(
        self,
        peer_id: str,
        *,
        local_peer_port: int,
        remote_hub_port: int | None = None,
        remote_client_port: int | None = None,
    ) -> None:
        self.tunnels[peer_id] = PeerTunnel(
            peer_id=peer_id,
            local_peer_port=local_peer_port,
            remote_hub_port=remote_hub_port,
            remote_client_port=remote_client_port,
        )

    def start_bootstrap(self, hub_host: str, hub_port: int) -> None:
        if self.bootstrap_worker is not None:
            return
        log_root = (self.config.path.parent if self.config.path is not None else self.config.workspace.root) / "logs" / "bootstrap"
        self.bootstrap_worker = HubBootstrapWorker(hub_host=hub_host, hub_port=hub_port, log_root=log_root)
        for collaborator in self.collaborators.values():
            self.reconcile_collaborator(collaborator.peer_id)

    async def close_bootstrap(self) -> None:
        for routed in list(self.tunnel_streams_by_caller.values()):
            if routed.task is not None:
                routed.task.cancel()
        for routed in list(self.tunnel_streams_by_caller.values()):
            if routed.task is not None:
                try:
                    await routed.task
                except asyncio.CancelledError:
                    pass
        self.tunnel_streams_by_caller.clear()
        for task in list(self.bootstrap_tasks.values()):
            task.cancel()
        for task in list(self.bootstrap_tasks.values()):
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.bootstrap_tasks.clear()
        if self.bootstrap_worker is not None:
            await asyncio.to_thread(self.bootstrap_worker.close)
        self.bootstrap_worker = None

    def reconcile_collaborator(self, peer_id: str) -> None:
        if self.bootstrap_worker is None:
            return
        if peer_id in self.peers and self.peers[peer_id].get("online") is True:
            return
        current = self.bootstrap_tasks.get(peer_id)
        if current is not None and not current.done():
            return
        collaborator = self.collaborators.get(peer_id)
        if collaborator is None:
            return
        self.bootstrap_states[peer_id] = {
            "status": "starting",
            "summary": "Bootstrap started",
            "updatedAt": int(time.time() * 1000),
            "checks": [{"id": "bootstrap", "status": "pending", "summary": "Bootstrap is running"}],
            "logPath": str(self.bootstrap_worker.log_root / f"{peer_id}.log") if self.bootstrap_worker.log_root is not None else None,
        }
        self.publish()
        self.bootstrap_tasks[peer_id] = asyncio.create_task(self._run_bootstrap(collaborator))

    async def _run_bootstrap(self, collaborator: CollaboratorRecord) -> None:
        assert self.bootstrap_worker is not None
        payload = collaborator.to_json()
        payload["remoteHubPort"] = self._remote_hub_port_for(collaborator.peer_id)
        payload["remoteClientPort"] = self._remote_client_port_for(collaborator.peer_id)
        try:
            result = await asyncio.to_thread(self.bootstrap_worker.bootstrap, payload)
        except Exception as exc:
            result = {"ok": False, "peerId": collaborator.peer_id, "status": "error", "summary": str(exc)}
        start = result.get("start", {})
        if isinstance(start, dict) and start.get("ok", False):
            self.register_tunnel(
                collaborator.peer_id,
                local_peer_port=int(start.get("localPort", 0)),
                remote_hub_port=int(start.get("remoteHubPort", 0)),
                remote_client_port=int(start.get("remotePort", 0)),
            )
        self.bootstrap_states[collaborator.peer_id] = self._bootstrap_state_from_result(collaborator.peer_id, result)
        self.publish()

    def _bootstrap_state_from_result(self, peer_id: str, result: dict[str, object]) -> dict[str, object]:
        status = str(result.get("status", "starting" if result.get("ok", False) else "error"))
        summary = str(result.get("summary", "Bootstrap is running" if status == "starting" else "Bootstrap failed"))
        log_path = None
        if self.bootstrap_worker is not None and self.bootstrap_worker.log_root is not None:
            log_path = str(self.bootstrap_worker.log_root / f"{peer_id}.log")
        checks = [{"id": "bootstrap", "status": "pending" if status == "starting" else "error", "summary": summary}]
        diagnostics = result.get("diagnostics", {})
        if isinstance(diagnostics, dict):
            for name in ("python", "uv", "git", "node", "npm"):
                value = diagnostics.get(name, {})
                if isinstance(value, dict):
                    checks.append({
                        "id": name,
                        "status": "ok" if value.get("ok") else "error",
                        "summary": str(value.get("summary", "")),
                    })
        start = result.get("start", {})
        if isinstance(start, dict):
            logs = start.get("logs", {})
            if isinstance(logs, dict):
                self._append_log_checks(checks, logs)
        return {
            "status": status,
            "summary": summary,
            "updatedAt": int(time.time() * 1000),
            "checks": checks,
            "logPath": log_path,
            "result": result,
        }

    def heartbeat(self, payload: dict[str, Any]) -> None:
        peer_id = str(payload.get("peerId", ""))
        if not peer_id:
            raise ValueError("peer.heartbeat requires peerId")
        peer = self.peers.get(peer_id)
        if peer is None:
            raise ValueError(f"peer is not registered: {peer_id}")
        peer["lastSeenAt"] = int(time.time() * 1000)
        peer["status"] = "online"
        peer["online"] = True
        peer["summary"] = "Connected"
        self.publish()

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
        mark_presence_offline(peer)
        self.publish()

    def peers_json(self) -> list[dict[str, object]]:
        merged = {} if self.config.mode == "hub" else {self.config.self_peer_id: dict(self.self_peer)}
        for collaborator in self.collaborators.values():
            merged[collaborator.peer_id] = configured_presence(collaborator)
        for peer_id, state in self.bootstrap_states.items():
            if peer_id not in merged:
                continue
            merged[peer_id] = {
                **merged[peer_id],
                "status": state["status"],
                "summary": state["summary"],
                "online": False,
            }
        for peer_id, peer in self.peers.items():
            merged[peer_id] = dict(peer)
        return sorted(merged.values(), key=lambda item: str(item["id"]))

    def collaborators_json(self) -> list[dict[str, object]]:
        return [item.to_json() for item in sorted(self.collaborators.values(), key=lambda item: item.peer_id)]

    def peer_health(self, payload: dict[str, Any]) -> dict[str, object]:
        peer_id = str(payload.get("peerId", ""))
        if not peer_id:
            raise ValueError("peer.health.get requires peerId")
        for peer in self.peers_json():
            if str(peer.get("id", "")) == peer_id:
                if peer_id in self.bootstrap_states and peer.get("online") is not True:
                    return {"health": self._bootstrap_health(peer_id, peer)}
                return {"health": health_for_presence(peer)}
        return {
            "health": {
                "peerId": peer_id,
                "status": "error",
                "summary": "Peer is not registered",
                "checks": [{"id": "config", "status": "error", "summary": "Peer record was not found"}],
                "updatedAt": int(time.time() * 1000),
            }
        }

    def upsert_collaborator(self, payload: dict[str, Any]) -> dict[str, object]:
        collaborator = CollaboratorRecord.from_json(payload)
        self.collaborators = {
            item.peer_id: item
            for item in upsert_collaborator(self.collaborators_path, collaborator)
        }
        self.reconcile_collaborator(collaborator.peer_id)
        self.publish()
        return collaborator.to_json()

    def remove_collaborator(self, peer_id: str) -> bool:
        existed = peer_id in self.collaborators
        self.collaborators = {
            item.peer_id: item
            for item in remove_collaborator(self.collaborators_path, peer_id)
        }
        task = self.bootstrap_tasks.pop(peer_id, None)
        if task is not None:
            task.cancel()
        self.bootstrap_states.pop(peer_id, None)
        self.publish()
        return existed

    def _remote_hub_port_for(self, peer_id: str) -> int:
        current = self.remote_hub_ports.get(peer_id)
        if current is not None:
            return current
        port = self._next_available_remote_port(self.remote_hub_ports, "_next_remote_hub_port")
        self.remote_hub_ports[peer_id] = port
        return port

    def _remote_client_port_for(self, peer_id: str) -> int:
        current = self.remote_client_ports.get(peer_id)
        if current is not None:
            return current
        port = self._next_available_remote_port(self.remote_client_ports, "_next_remote_client_port")
        self.remote_client_ports[peer_id] = port
        return port

    def _next_available_remote_port(self, assigned: dict[str, int], attr: str) -> int:
        current = int(getattr(self, attr))
        used = set(assigned.values())
        while current in used:
            current += 1
        setattr(self, attr, current + 1)
        return current

    def _bootstrap_health(self, peer_id: str, peer: dict[str, object]) -> dict[str, object]:
        state = self.bootstrap_states[peer_id]
        checks = list(state.get("checks", []))
        log_path = state.get("logPath")
        if log_path:
            checks.append({"id": "log", "status": "ok", "summary": str(log_path)})
        return {
            "peerId": peer_id,
            "status": str(state["status"]),
            "summary": str(peer.get("summary", state.get("summary", ""))),
            "checks": checks,
            "updatedAt": int(state.get("updatedAt", int(time.time() * 1000))),
        }

    def _append_log_checks(self, checks: list[dict[str, object]], logs: dict[str, object]) -> None:
        remote = logs.get("remote", {})
        if isinstance(remote, dict):
            for name in ("stdout", "stderr"):
                value = remote.get(name, {})
                if not isinstance(value, dict):
                    continue
                text = str(value.get("text") or value.get("error") or "")
                path = str(value.get("path", ""))
                checks.append({
                    "id": f"remote-{name}",
                    "status": "ok" if value.get("ok") else "error",
                    "summary": f"{path}\n{text}".rstrip(),
                })
        for name in ("sshStdout", "sshStderr"):
            text = str(logs.get(name, "")).strip()
            if text:
                checks.append({"id": name, "status": "error", "summary": text})

    def _load_collaborators(self) -> dict[str, CollaboratorRecord]:
        records = {item.peer_id: item for item in load_collaborators(self.collaborators_path)}
        for value in self.config.peers:
            try:
                record = CollaboratorRecord.from_json(dict(value))
            except ValueError:
                continue
            records.setdefault(record.peer_id, record)
        return records

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
            return
        if not method:
            await caller.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-method", "routed request requires method"),
            ))
            return
        tunnel = self.tunnels.get(target_peer_id)
        if tunnel is not None:
            if not self._peer_is_online(target_peer_id):
                await caller.send(ProtocolEnvelope.error_response(
                    message_id=envelope.message_id,
                    method=envelope.method,
                    error=ErrorInfo("peer-starting", f"target peer is not registered online: {target_peer_id}"),
                ))
                return
            await self._route_request_via_tunnel(caller, envelope, tunnel, method, payload)
            return
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

    async def _route_request_via_tunnel(
        self,
        caller: HubConnection,
        envelope: ProtocolEnvelope,
        tunnel: PeerTunnel,
        method: str,
        payload: dict[str, Any],
    ) -> None:
        message_id = self._next_relay_message_id()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(tunnel.ws_url) as ws:
                    await ws.send_json(envelope_to_json(ProtocolEnvelope.request(
                        message_id=message_id,
                        method=method,
                        payload=payload,
                    )))
                    response = await ws.receive_json(timeout=self.route_request_timeout_seconds)
        except Exception as exc:
            await caller.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("peer-tunnel-error", str(exc)),
            ))
            return
        try:
            routed = envelope_from_json(response)
        except Exception as exc:
            await caller.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("bad-target-response", str(exc)),
            ))
            return
        if routed.kind == "error":
            await caller.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=routed.error or ErrorInfo("target-error", "target returned an error"),
            ))
            return
        await caller.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method or "hub.route.request",
            payload=routed.payload,
        ))

    async def route_subscribe(self, caller: HubConnection, envelope: ProtocolEnvelope) -> None:
        if not envelope.stream_id:
            await caller.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "hub.route.subscribe requires streamId"),
            ))
            return
        target_peer_id = str(envelope.payload.get("targetPeerId", ""))
        method = str(envelope.payload.get("method", ""))
        payload_value = envelope.payload.get("payload", {})
        payload = dict(payload_value) if isinstance(payload_value, dict) else {}
        tunnel = self.tunnels.get(target_peer_id)
        if tunnel is not None:
            if not self._peer_is_online(target_peer_id):
                await caller.send(ProtocolEnvelope.stream_event(
                    message_id=envelope.message_id,
                    method=envelope.method or "hub.route.subscribe",
                    stream_id=envelope.stream_id,
                    event=StreamEvent(
                        stream_id=envelope.stream_id,
                        seq=0,
                        event="error",
                        payload={
                            "code": "peer-starting",
                            "message": f"target peer is not registered online: {target_peer_id}",
                        },
                    ),
                ))
                return
            if not method:
                await caller.send(ProtocolEnvelope.stream_event(
                    message_id=envelope.message_id,
                    method=envelope.method or "hub.route.subscribe",
                    stream_id=envelope.stream_id,
                    event=StreamEvent(
                        stream_id=envelope.stream_id,
                        seq=0,
                        event="error",
                        payload={"code": "missing-method", "message": "routed subscription requires method"},
                    ),
                ))
                return
            await self._route_subscribe_via_tunnel(caller, envelope, tunnel, method, payload)
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

    async def _route_subscribe_via_tunnel(
        self,
        caller: HubConnection,
        envelope: ProtocolEnvelope,
        tunnel: PeerTunnel,
        method: str,
        payload: dict[str, Any],
    ) -> None:
        assert envelope.stream_id is not None
        target_message_id = self._next_relay_message_id()
        target_stream_id = self._next_relay_stream_id()
        stream = TunnelRoutedStream(
            caller=caller,
            caller_message_id=envelope.message_id,
            caller_stream_id=envelope.stream_id,
            caller_method=envelope.method or "hub.route.subscribe",
            target_stream_id=target_stream_id,
        )
        previous = self.tunnel_streams_by_caller.pop(envelope.stream_id, None)
        if previous is not None and previous.task is not None:
            previous.task.cancel()
        self.tunnel_streams_by_caller[envelope.stream_id] = stream
        stream.task = asyncio.create_task(self._run_tunnel_stream(tunnel, stream, target_message_id, method, payload))

    async def _run_tunnel_stream(
        self,
        tunnel: PeerTunnel,
        stream: TunnelRoutedStream,
        target_message_id: str,
        method: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            async with ClientSession() as session:
                async with session.ws_connect(tunnel.ws_url) as ws:
                    await ws.send_json(envelope_to_json(ProtocolEnvelope(
                        message_id=target_message_id,
                        kind="request",
                        method=method,
                        stream_id=stream.target_stream_id,
                        payload=payload,
                    )))
                    async for msg in ws:
                        if msg.type != WSMsgType.TEXT:
                            continue
                        envelope = envelope_from_json(json.loads(msg.data))
                        if envelope.kind == "stream-event" and envelope.stream_id == stream.target_stream_id:
                            event = StreamEvent(
                                stream_id=stream.caller_stream_id,
                                seq=int(envelope.payload.get("seq", 0)),
                                event=str(envelope.payload.get("event", "message")),
                                payload=dict(envelope.payload.get("payload", {})),
                            )
                            await stream.caller.send(ProtocolEnvelope.stream_event(
                                message_id=stream.caller_message_id,
                                method=stream.caller_method,
                                stream_id=stream.caller_stream_id,
                                event=event,
                            ))
                        elif envelope.kind == "error":
                            await self._send_tunnel_stream_error(
                                stream,
                                envelope.error.code if envelope.error is not None else "target-error",
                                envelope.error.message if envelope.error is not None else "target returned an error",
                            )
                            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._send_tunnel_stream_error(stream, "peer-tunnel-error", str(exc))
        finally:
            if self.tunnel_streams_by_caller.get(stream.caller_stream_id) is stream:
                self.tunnel_streams_by_caller.pop(stream.caller_stream_id, None)

    async def _send_tunnel_stream_error(self, stream: TunnelRoutedStream, code: str, message: str) -> None:
        await stream.caller.send(ProtocolEnvelope.stream_event(
            message_id=stream.caller_message_id,
            method=stream.caller_method,
            stream_id=stream.caller_stream_id,
            event=StreamEvent(
                stream_id=stream.caller_stream_id,
                seq=0,
                event="error",
                payload={"code": code, "message": message},
            ),
        ))

    async def open_diff_stream(
        self,
        caller: HubConnection,
        message_id: str,
        stream_id: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            left = endpoint_from_json(payload["left"])
            right = endpoint_from_json(payload["right"])
            window = window_from_json(payload["window"])
            context_lines = int(payload.get("contextLines", 3))
        except Exception as exc:
            await caller.send(ProtocolEnvelope.error_response(
                message_id=message_id,
                method="diff.subscribe",
                error=ErrorInfo("bad-request", str(exc)),
            ))
            return
        stream = HubDiffStream(
            caller=caller,
            message_id=message_id,
            stream_id=stream_id,
            diff_id=format_diff_id(len(caller.diff_streams) + 1),
            left=left,
            right=right,
            window=window,
            context_lines=context_lines,
        )
        caller.diff_streams[stream_id] = stream
        await self._open_diff_source(stream, "left", left)
        await self._open_diff_source(stream, "right", right)

    async def update_diff_window(self, caller: HubConnection, payload: dict[str, Any]) -> bool:
        stream = caller.diff_streams.get(str(payload.get("streamId", "")))
        if stream is None:
            return False
        stream.window = window_from_json(payload["window"])
        read_window = effective_window(stream.window, stream.context_lines)
        for target, target_stream_id in [
            (stream.left_target, stream.left_target_stream_id),
            (stream.right_target, stream.right_target_stream_id),
        ]:
            if target is None or target_stream_id is None:
                continue
            await target.send(ProtocolEnvelope.request(
                message_id=self._next_relay_message_id(),
                method="file.window.update",
                payload={
                    "streamId": target_stream_id,
                    "window": {"lineStart": read_window.line_start, "lineEnd": read_window.line_end},
                },
            ))
        return True

    async def close_diff_stream(self, caller: HubConnection, stream_id: str) -> bool:
        stream = caller.diff_streams.pop(stream_id, None)
        if stream is None:
            return False
        await self._close_diff_stream(stream)
        return True

    async def close_connection_diff_streams(self, caller: HubConnection) -> None:
        streams = list(caller.diff_streams.values())
        caller.diff_streams.clear()
        for stream in streams:
            await self._close_diff_stream(stream)

    async def _open_diff_source(self, stream: HubDiffStream, side: str, endpoint: DiffEndpoint) -> None:
        target = self.connections.get(endpoint.peer_id)
        if target is None:
            await self._publish_diff_diagnostic(
                stream,
                "peer-offline",
                f"source peer is not connected: {endpoint.peer_id}",
                side,
                {"peerId": endpoint.peer_id},
            )
            return
        target_stream_id = self._next_relay_stream_id()
        if side == "left":
            stream.left_target = target
            stream.left_target_stream_id = target_stream_id
        else:
            stream.right_target = target
            stream.right_target_stream_id = target_stream_id
        self.diff_sources_by_target_stream[target_stream_id] = (stream, side)
        read_window = effective_window(stream.window, stream.context_lines)
        await target.send(ProtocolEnvelope(
            message_id=self._next_relay_message_id(),
            kind="request",
            method="file.subscribe",
            stream_id=target_stream_id,
            payload={
                "repoPath": endpoint.repo_path,
                "path": endpoint.path,
                "ref": endpoint.ref.kind,
                "window": {"lineStart": read_window.line_start, "lineEnd": read_window.line_end},
            },
        ))

    async def _close_diff_stream(self, stream: HubDiffStream) -> None:
        for target, target_stream_id in [
            (stream.left_target, stream.left_target_stream_id),
            (stream.right_target, stream.right_target_stream_id),
        ]:
            if target_stream_id is not None:
                self.diff_sources_by_target_stream.pop(target_stream_id, None)
            if target is None or target_stream_id is None:
                continue
            await target.send(ProtocolEnvelope.request(
                message_id=self._next_relay_message_id(),
                method="file.unsubscribe",
                payload={"streamId": target_stream_id},
            ))

    async def handle_diff_source_event(self, target: HubConnection, envelope: ProtocolEnvelope) -> bool:
        if not envelope.stream_id:
            return False
        source = self.diff_sources_by_target_stream.get(envelope.stream_id)
        if source is None:
            return False
        stream, side = source
        expected_target = stream.left_target if side == "left" else stream.right_target
        if expected_target is not target:
            return False
        event = str(envelope.payload.get("event", ""))
        payload = dict(envelope.payload.get("payload", {}))
        try:
            if event == "snapshot":
                snapshot = text_window_snapshot_from_json(payload)
            elif event == "delta":
                current = stream.left_snapshot if side == "left" else stream.right_snapshot
                if current is None:
                    return True
                snapshot = apply_text_window_delta(current, text_window_delta_from_json(payload))
            elif event == "reset":
                snapshot = reset_from_json(payload).snapshot
            elif event == "error":
                await self._publish_diff_diagnostic(
                    stream,
                    str(payload.get("code", "peer-offline")),
                    str(payload.get("message", "source stream error")),
                    side,
                    dict(payload.get("details", {})),
                )
                return True
            else:
                return True
        except Exception as exc:
            await self._publish_diff_diagnostic(
                stream,
                "decode-failed",
                f"{side} source payload could not be applied: {exc}",
                side,
                {"event": event},
            )
            return True
        if side == "left":
            stream.left_snapshot = snapshot
        else:
            stream.right_snapshot = snapshot
        await self._publish_diff_if_ready(stream)
        return True

    async def _publish_diff_if_ready(self, stream: HubDiffStream) -> None:
        if stream.left_snapshot is None or stream.right_snapshot is None:
            return
        try:
            left_lines = _snapshot_lines(stream.left_snapshot)
            right_lines = _snapshot_lines(stream.right_snapshot)
            stream.version += 1
            payload = diff_payload_from_snapshots(stream, left_lines, right_lines, [])
        except Exception as exc:
            await self._publish_diff_diagnostic(
                stream,
                "decode-failed",
                f"source text could not be decoded: {exc}",
                None,
                {},
            )
            return
        await self._send_diff_payload(stream, payload)

    async def _publish_diff_diagnostic(
        self,
        stream: HubDiffStream,
        code: str,
        message: str,
        endpoint: str | None,
        details: dict[str, Any],
    ) -> None:
        stream.version += 1
        payload = diff_payload_from_snapshots(
            stream,
            [],
            [],
            [DiffDiagnostic(code=code, message=message, endpoint=endpoint, details=details)],
        )
        await self._send_diff_payload(stream, payload)

    async def _send_diff_payload(self, stream: HubDiffStream, payload: DiffPayload) -> None:
        stream.seq += 1
        await stream.caller.send(ProtocolEnvelope.stream_event(
            message_id=stream.message_id,
            method="diff.subscribe",
            stream_id=stream.stream_id,
            event=StreamEvent(
                stream_id=stream.stream_id,
                seq=stream.seq,
                event="snapshot",
                payload=payload_to_json(payload),
            ),
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
        if await self.handle_diff_source_event(target, envelope):
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

    def _peer_is_online(self, peer_id: str) -> bool:
        peer = self.peers.get(peer_id)
        return bool(peer and peer.get("online") is True and peer.get("status") == "online")

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
        for target_stream_id, (stream, side) in list(self.diff_sources_by_target_stream.items()):
            expected_target = stream.left_target if side == "left" else stream.right_target
            if expected_target is not target:
                continue
            self.diff_sources_by_target_stream.pop(target_stream_id, None)
            await self._publish_diff_diagnostic(stream, code, message, side, {})

    def _remove_caller_routes(self, caller: HubConnection) -> None:
        for target_stream_id, routed in list(self.routed_streams_by_target.items()):
            if routed.caller is not caller:
                continue
            self.routed_streams_by_target.pop(target_stream_id, None)
            self.routed_streams_by_caller.pop(routed.caller_stream_id, None)
        for caller_stream_id, routed in list(self.tunnel_streams_by_caller.items()):
            if routed.caller is not caller:
                continue
            self.tunnel_streams_by_caller.pop(caller_stream_id, None)
            if routed.task is not None:
                routed.task.cancel()
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


def diff_payload_from_snapshots(
    stream: HubDiffStream,
    left_lines: list[str],
    right_lines: list[str],
    diagnostics: list[DiffDiagnostic],
) -> DiffPayload:
    if diagnostics:
        payload = DiffPayload(
            diff_id=stream.diff_id,
            version=format_diff_version(stream.version),
            left=source_state_from_snapshot(stream.left, stream.left_snapshot),
            right=source_state_from_snapshot(stream.right, stream.right_snapshot),
            window=stream.window,
            hunks=[],
            diagnostics=diagnostics,
        )
        payload.validate()
        return payload
    return build_diff_payload(
        diff_id=stream.diff_id,
        version=format_diff_version(stream.version),
        left=source_state_from_snapshot(stream.left, stream.left_snapshot),
        right=source_state_from_snapshot(stream.right, stream.right_snapshot),
        window=stream.window,
        left_lines=left_lines,
        right_lines=right_lines,
        context_lines=stream.context_lines,
    )


def source_state_from_snapshot(endpoint: DiffEndpoint, snapshot: TextWindowSnapshot | None) -> DiffSourceState:
    if snapshot is None:
        return DiffSourceState(endpoint=endpoint, file_version="fv000000", content_hash="sha256:unavailable")
    return DiffSourceState(endpoint=endpoint, file_version=snapshot.file_version, content_hash=snapshot.content_hash)


def _snapshot_lines(snapshot: TextWindowSnapshot) -> list[str]:
    return snapshot.data.decode("utf-8").splitlines()

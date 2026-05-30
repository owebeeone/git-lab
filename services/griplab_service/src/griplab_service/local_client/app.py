"""aiohttp local client app for health, probe, and service protocol streams."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import re
import signal
import subprocess
import struct
import termios
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - Windows hardening is deferred.
    resource = None  # type: ignore[assignment]

from aiohttp import WSMsgType, web
from aiohttp.client_exceptions import ClientConnectionResetError
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from filedelta import (
    FileConnection,
    LineWindow,
    ResetEvent,
    TextWindowDelta,
    TextWindowSnapshot,
    reset_to_json,
    text_window_delta_to_json,
    text_window_snapshot_to_json,
)
from griplab_service.chat_store import ChatStore, chat_store_root
from griplab_service.collaborators import health_for_presence
from griplab_service.config import ServiceConfig
from griplab_service.local_client.deps import DependencyGraph, get_dependency_graph
from griplab_service.local_client.tree import TreeWatchRegistry, tree_snapshot_payload
from griplab_service.local_client.workspace import ChangedFile, RepoStatus, collect_workspace_status
from griplab_service.probe import build_probe
from griplab_service.protocol import (
    ErrorInfo,
    ProtocolEnvelope,
    ProtocolValidationError,
    StreamEvent,
    envelope_from_json,
    envelope_to_json,
)
from griplab_service.restart import schedule_process_restart
from griplab_service.ssh_bootstrap import EphemeralBootstrapManager, probe_peer

CONFIG_KEY = web.AppKey("config", ServiceConfig)
SESSIONS_KEY = web.AppKey("sessions", Any)
BOOTSTRAPS_KEY = web.AppKey("bootstraps", Any)
CHAT_KEY = web.AppKey("chat", Any)
TREE_WATCH_KEY = web.AppKey("tree_watch", TreeWatchRegistry)


class LocalClientServer:
    """Local aiohttp server used by the browser client and tests."""

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
            raise RuntimeError("local client server did not start")

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
    app[SESSIONS_KEY] = SessionManager(config)
    app[BOOTSTRAPS_KEY] = EphemeralBootstrapManager()
    app[CHAT_KEY] = ChatStore(chat_store_root(config.path, config.workspace.root))
    app[TREE_WATCH_KEY] = TreeWatchRegistry(config.workspace.root, asyncio.get_running_loop())
    app.on_cleanup.append(cleanup_app)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/probe", handle_probe)
    app.router.add_get("/workspace/status", handle_workspace_status)
    app.router.add_get("/deps", handle_deps)
    app.router.add_get("/ws", handle_ws)
    return app


async def cleanup_app(app: web.Application) -> None:
    await app[TREE_WATCH_KEY].close()
    app[BOOTSTRAPS_KEY].close()


async def handle_health(request: web.Request) -> web.Response:
    config = request.app[CONFIG_KEY]
    return web.json_response({"ok": True, "mode": config.mode})


async def handle_probe(request: web.Request) -> web.Response:
    config = request.app[CONFIG_KEY]
    return web.json_response(build_probe(config))


async def handle_workspace_status(request: web.Request) -> web.Response:
    config = request.app[CONFIG_KEY]
    return web.json_response(workspace_status_payload(config))


async def handle_deps(request: web.Request) -> web.Response:
    config = request.app[CONFIG_KEY]
    return web.json_response(deps_payload(config))


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    config = request.app[CONFIG_KEY]
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    connection = LocalClientConnection(
        config,
        request.app[SESSIONS_KEY],
        request.app[BOOTSTRAPS_KEY],
        request.app[CHAT_KEY],
        request.app[TREE_WATCH_KEY],
        ws,
    )

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


async def handle_protocol_message(
    connection: "LocalClientConnection",
    envelope: ProtocolEnvelope,
) -> None:
    if envelope.kind != "request":
        await connection.send(ProtocolEnvelope.error_response(
            message_id=envelope.message_id,
            method=envelope.method,
            error=ErrorInfo("bad-kind", "only request envelopes are accepted by the local client"),
        ))
        return
    if envelope.method == "deps.get":
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload=deps_payload(connection.config),
        ))
        return
    if envelope.method == "admin.restart":
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"restarting": True, "target": "client"},
        ))
        schedule_process_restart()
        return
    if envelope.method == "workspace.status.subscribe":
        if not envelope.stream_id:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "workspace.status.subscribe requires streamId"),
            ))
            return
        await connection.subscribe_workspace_status(envelope.message_id, envelope.stream_id)
        return
    if envelope.method == "workspace.status.refresh":
        refreshed = await connection.refresh_workspace_status(envelope.message_id)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"refreshed": refreshed},
        ))
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
    if envelope.method == "peer.presence.subscribe":
        if not envelope.stream_id:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "peer.presence.subscribe requires streamId"),
            ))
            return
        await connection.subscribe_peers(envelope.message_id, envelope.stream_id)
        return
    if envelope.method == "peer.health.get":
        try:
            payload = peer_health_payload(connection.config, envelope.payload)
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
    if envelope.method == "chat.post":
        try:
            message = connection.chat_store.post(
                envelope.payload,
                default_sender_id=connection.config.self_peer_id,
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
    if envelope.method == "tree.subscribe":
        if not envelope.stream_id:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "tree.subscribe requires streamId"),
            ))
            return
        await connection.subscribe_tree(envelope.message_id, envelope.stream_id)
        return
    if envelope.method == "tree.refresh":
        refreshed = await connection.refresh_tree(envelope.message_id)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"refreshed": refreshed},
        ))
        return
    if envelope.method == "tree.unsubscribe":
        stream_id = str(envelope.payload.get("streamId", ""))
        stopped = await connection.unsubscribe_tree(stream_id)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"stopped": stopped},
        ))
        return
    if envelope.method == "file.subscribe":
        if not envelope.stream_id:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "file.subscribe requires streamId"),
            ))
            return
        await connection.subscribe_file(envelope.message_id, envelope.stream_id, envelope.payload)
        return
    if envelope.method == "file.window.update":
        stream_id = str(envelope.payload.get("streamId", ""))
        updated = await connection.update_file_window(stream_id, envelope.payload)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"updated": updated},
        ))
        return
    if envelope.method == "file.unsubscribe":
        stream_id = str(envelope.payload.get("streamId", ""))
        stopped = await connection.unsubscribe_file(stream_id)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"stopped": stopped},
        ))
        return
    if envelope.method == "sessions.subscribe":
        if not envelope.stream_id:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "sessions.subscribe requires streamId"),
            ))
            return
        await connection.subscribe_sessions(envelope.message_id, envelope.stream_id)
        return
    if envelope.method == "session.output.subscribe":
        if not envelope.stream_id:
            await connection.send(ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "session.output.subscribe requires streamId"),
            ))
            return
        await connection.subscribe_session_output(envelope.message_id, envelope.stream_id, envelope.payload)
        return
    if envelope.method == "cmd.run":
        session_id = await connection.session_manager.run_command(envelope.payload)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"sessionId": session_id},
        ))
        return
    if envelope.method == "sessions.query":
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload=connection.session_manager.query(envelope.payload),
        ))
        return
    if envelope.method == "peer.probe":
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload=await asyncio.to_thread(probe_peer, envelope.payload),
        ))
        return
    if envelope.method == "peer.bootstrap":
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload=await asyncio.to_thread(connection.bootstraps.bootstrap, envelope.payload),
        ))
        return
    if envelope.method == "peer.bootstrap.stop":
        bootstrap_id = str(envelope.payload.get("bootstrapId", ""))
        stopped = await asyncio.to_thread(connection.bootstraps.stop, bootstrap_id)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"stopped": stopped},
        ))
        return
    if envelope.method == "term.open":
        session_id = await connection.session_manager.open_terminal(envelope.payload)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"sessionId": session_id},
        ))
        return
    if envelope.method == "term.input":
        written = connection.session_manager.terminal_input(envelope.payload)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"written": written},
        ))
        return
    if envelope.method == "term.resize":
        resized = connection.session_manager.terminal_resize(envelope.payload)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"resized": resized},
        ))
        return
    if envelope.method == "term.close":
        closed = await connection.session_manager.terminal_close(envelope.payload)
        await connection.send(ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload={"closed": closed},
        ))
        return
    await connection.send(ProtocolEnvelope.error_response(
        message_id=envelope.message_id,
        method=envelope.method,
        error=ErrorInfo("unknown-method", f"unknown method: {envelope.method}"),
    ))


@dataclass
class WorkspaceStatusStream:
    message_id: str
    stream_id: str
    seq: int = 0
    last_hash: str | None = None
    task: asyncio.Task[None] | None = None


@dataclass
class TreeStream:
    message_id: str
    stream_id: str
    seq: int = 0
    last_hash: str | None = None
    task: asyncio.Task[None] | None = None
    queue: asyncio.Queue[None] | None = None


@dataclass
class FileStream:
    message_id: str
    stream_id: str
    connection: FileConnection | None = None
    subscription: Any | None = None
    task: asyncio.Task[None] | None = None
    watcher: "FileWatcher" | None = None
    queue: asyncio.Queue[None] | None = None
    temp_path: Path | None = None


@dataclass
class SessionsStream:
    message_id: str
    stream_id: str
    queue: asyncio.Queue[None]
    seq: int = 0
    task: asyncio.Task[None] | None = None


@dataclass
class SessionOutputStream:
    message_id: str
    stream_id: str
    session_id: str
    repo_path: str
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
class PeerStream:
    message_id: str
    stream_id: str
    seq: int = 0


class LocalClientConnection:
    def __init__(
        self,
        config: ServiceConfig,
        session_manager: "SessionManager",
        bootstraps: EphemeralBootstrapManager,
        chat_store: ChatStore,
        tree_watches: TreeWatchRegistry,
        ws: web.WebSocketResponse,
    ) -> None:
        self.config = config
        self.session_manager = session_manager
        self.bootstraps = bootstraps
        self.chat_store = chat_store
        self.tree_watches = tree_watches
        self.ws = ws
        self.workspace_status_streams: dict[str, WorkspaceStatusStream] = {}
        self.tree_streams: dict[str, TreeStream] = {}
        self.file_streams: dict[str, FileStream] = {}
        self.sessions_streams: dict[str, SessionsStream] = {}
        self.output_streams: dict[str, SessionOutputStream] = {}
        self.chat_streams: dict[str, ChatStream] = {}
        self.peer_streams: dict[str, PeerStream] = {}
        self._send_lock = asyncio.Lock()

    async def send(self, envelope: ProtocolEnvelope) -> None:
        if self.ws.closed:
            return
        async with self._send_lock:
            if self.ws.closed:
                return
            try:
                await self.ws.send_json(envelope_to_json(envelope))
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError):
                return
            except RuntimeError as exc:
                if is_closing_transport_error(exc):
                    return
                raise

    async def subscribe_workspace_status(self, message_id: str, stream_id: str) -> None:
        existing = self.workspace_status_streams.get(stream_id)
        if existing is not None:
            await self._publish_workspace_status(existing, force=True)
            return
        stream = WorkspaceStatusStream(message_id=message_id, stream_id=stream_id)
        self.workspace_status_streams[stream_id] = stream
        await self._publish_workspace_status(stream, force=True)
        stream.task = asyncio.create_task(self._poll_workspace_status(stream))

    async def refresh_workspace_status(self, message_id: str) -> int:
        del message_id
        count = 0
        for stream in list(self.workspace_status_streams.values()):
            await self._publish_workspace_status(stream, force=True)
            count += 1
        return count

    async def subscribe_tree(self, message_id: str, stream_id: str) -> None:
        existing = self.tree_streams.get(stream_id)
        if existing is not None:
            await self._publish_tree(existing, force=True)
            return
        queue: asyncio.Queue[None] = asyncio.Queue()
        stream = TreeStream(message_id=message_id, stream_id=stream_id, queue=queue)
        self.tree_streams[stream_id] = stream
        await self._publish_tree(stream, force=True)
        self.tree_watches.subscribe(queue)
        stream.task = asyncio.create_task(self._watch_tree(stream))

    async def refresh_tree(self, message_id: str) -> int:
        del message_id
        count = 0
        for stream in list(self.tree_streams.values()):
            await self._publish_tree(stream, force=True)
            count += 1
        return count

    async def unsubscribe_tree(self, stream_id: str) -> bool:
        stream = self.tree_streams.pop(stream_id, None)
        if stream is None:
            return False
        await self._close_tree_stream(stream)
        return True

    async def subscribe_file(self, message_id: str, stream_id: str, payload: dict[str, Any]) -> None:
        existing = self.file_streams.get(stream_id)
        if existing is not None:
            await self._close_file_stream(existing, "replaced")
            self.file_streams.pop(stream_id, None)

        stream = FileStream(message_id=message_id, stream_id=stream_id)
        self.file_streams[stream_id] = stream
        try:
            source = resolve_file_source(self.config.workspace.root, payload)
            stream.temp_path = source.get("temp_path") if isinstance(source.get("temp_path"), Path) else None
            window = parse_line_window(payload)
            queue: asyncio.Queue[None] = asyncio.Queue()
            stream.queue = queue
            subscriber = ServiceFileSubscriber(self, stream)
            connection = FileConnection(str(source["resource_id"]), source["path"])
            stream.connection = connection
            await connection.open()
            stream.subscription = await connection.subscribe_window(subscriber, window)
            if source["ref"] == "working":
                watcher = FileWatcher(Path(source["path"]), asyncio.get_running_loop(), queue)
                stream.watcher = watcher
                watcher.start()
                stream.task = asyncio.create_task(self._watch_file(stream))
        except Exception as exc:
            if stream.temp_path is not None:
                stream.temp_path.unlink(missing_ok=True)
                stream.temp_path = None
            code = "unsupported-ref" if str(exc).startswith("unsupported ref:") else "file-open-failed"
            await self._send_file_error(stream, code, str(exc))

    async def update_file_window(self, stream_id: str, payload: dict[str, Any]) -> bool:
        stream = self.file_streams.get(stream_id)
        if stream is None or stream.subscription is None:
            return False
        await stream.subscription.update_window(parse_line_window(payload))
        return True

    async def unsubscribe_file(self, stream_id: str) -> bool:
        stream = self.file_streams.pop(stream_id, None)
        if stream is None:
            return False
        await self._close_file_stream(stream, "unsubscribed")
        return True

    async def subscribe_sessions(self, message_id: str, stream_id: str) -> None:
        existing = self.sessions_streams.get(stream_id)
        if existing is not None:
            await self._publish_sessions(existing)
            return
        queue = self.session_manager.add_sessions_subscriber()
        stream = SessionsStream(message_id=message_id, stream_id=stream_id, queue=queue)
        self.sessions_streams[stream_id] = stream
        await self._publish_sessions(stream)
        stream.task = asyncio.create_task(self._watch_sessions(stream))

    async def subscribe_session_output(self, message_id: str, stream_id: str, payload: dict[str, Any]) -> None:
        session_id = str(payload.get("sessionId", ""))
        repo_path = str(payload.get("repoPath", ""))
        queue = self.session_manager.add_output_subscriber(session_id, repo_path)
        stream = SessionOutputStream(
            message_id=message_id,
            stream_id=stream_id,
            session_id=session_id,
            repo_path=repo_path,
            queue=queue,
        )
        self.output_streams[stream_id] = stream
        await self._publish_session_output(stream)
        stream.task = asyncio.create_task(self._watch_session_output(stream))

    async def subscribe_chat(self, message_id: str, stream_id: str) -> None:
        existing = self.chat_streams.get(stream_id)
        if existing is not None:
            await self._publish_chat(existing)
            return
        queue: asyncio.Queue[None] = asyncio.Queue()
        self.chat_store.add_subscriber(queue)
        stream = ChatStream(message_id=message_id, stream_id=stream_id, queue=queue)
        self.chat_streams[stream_id] = stream
        await self._publish_chat(stream)
        stream.task = asyncio.create_task(self._watch_chat(stream))

    async def subscribe_peers(self, message_id: str, stream_id: str) -> None:
        stream = PeerStream(message_id=message_id, stream_id=stream_id)
        self.peer_streams[stream_id] = stream
        await self._publish_peers(stream)

    async def close(self) -> None:
        status_tasks = [stream.task for stream in self.workspace_status_streams.values() if stream.task is not None]
        tree_streams = list(self.tree_streams.values())
        file_streams = list(self.file_streams.values())
        sessions_streams = list(self.sessions_streams.values())
        output_streams = list(self.output_streams.values())
        chat_streams = list(self.chat_streams.values())
        self.workspace_status_streams.clear()
        self.tree_streams.clear()
        self.file_streams.clear()
        self.sessions_streams.clear()
        self.output_streams.clear()
        self.chat_streams.clear()
        self.peer_streams.clear()
        for stream in tree_streams:
            await self._close_tree_stream(stream)
        for stream in file_streams:
            await self._close_file_stream(stream, "closed")
        for stream in sessions_streams:
            self.session_manager.remove_sessions_subscriber(stream.queue)
            if stream.task is not None:
                stream.task.cancel()
        for stream in output_streams:
            self.session_manager.remove_output_subscriber(stream.session_id, stream.repo_path, stream.queue)
            if stream.task is not None:
                stream.task.cancel()
        for stream in chat_streams:
            self.chat_store.remove_subscriber(stream.queue)
            if stream.task is not None:
                stream.task.cancel()
        tasks = status_tasks + [
            stream.task for stream in sessions_streams + output_streams + chat_streams if stream.task is not None
        ]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _poll_workspace_status(self, stream: WorkspaceStatusStream) -> None:
        interval = self.config.workspace.status_poll_interval_ms / 1000
        try:
            while stream.stream_id in self.workspace_status_streams:
                await asyncio.sleep(interval)
                await self._publish_workspace_status(stream, force=False)
        except asyncio.CancelledError:
            raise

    async def _watch_tree(self, stream: TreeStream) -> None:
        assert stream.queue is not None
        try:
            while stream.stream_id in self.tree_streams:
                try:
                    await asyncio.wait_for(stream.queue.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(0.05)
                while not stream.queue.empty():
                    stream.queue.get_nowait()
                await self._publish_tree(stream, force=False)
        except asyncio.CancelledError:
            raise

    async def _close_tree_stream(self, stream: TreeStream) -> None:
        if stream.task is not None:
            stream.task.cancel()
            try:
                await stream.task
            except asyncio.CancelledError:
                pass
        if stream.queue is not None:
            self.tree_watches.unsubscribe(stream.queue)

    async def _watch_file(self, stream: FileStream) -> None:
        assert stream.queue is not None
        assert stream.connection is not None
        try:
            while stream.stream_id in self.file_streams:
                await stream.queue.get()
                await asyncio.sleep(0.05)
                while not stream.queue.empty():
                    stream.queue.get_nowait()
                await stream.connection.file_changed()
        except asyncio.CancelledError:
            raise

    async def _close_file_stream(self, stream: FileStream, reason: str) -> None:
        if stream.task is not None:
            stream.task.cancel()
            try:
                await stream.task
            except asyncio.CancelledError:
                pass
        if stream.watcher is not None:
            stream.watcher.stop()
        if stream.connection is not None:
            await stream.connection.close(reason)
        if stream.temp_path is not None:
            stream.temp_path.unlink(missing_ok=True)
            stream.temp_path = None

    async def _watch_sessions(self, stream: SessionsStream) -> None:
        try:
            while stream.stream_id in self.sessions_streams:
                await stream.queue.get()
                await self._publish_sessions(stream)
        except asyncio.CancelledError:
            raise

    async def _watch_session_output(self, stream: SessionOutputStream) -> None:
        try:
            while stream.stream_id in self.output_streams:
                await stream.queue.get()
                await self._publish_session_output(stream)
        except asyncio.CancelledError:
            raise

    async def _watch_chat(self, stream: ChatStream) -> None:
        try:
            while stream.stream_id in self.chat_streams:
                await stream.queue.get()
                await self._publish_chat(stream)
        except asyncio.CancelledError:
            raise

    async def _publish_sessions(self, stream: SessionsStream) -> None:
        stream.seq += 1
        await self.send(ProtocolEnvelope.stream_event(
            message_id=stream.message_id,
            method="sessions.subscribe",
            stream_id=stream.stream_id,
            event=StreamEvent(
                stream_id=stream.stream_id,
                seq=stream.seq,
                event="snapshot",
                payload={"sessions": self.session_manager.sessions_json()},
            ),
        ))

    async def _publish_session_output(self, stream: SessionOutputStream) -> None:
        stream.seq += 1
        await self.send(ProtocolEnvelope.stream_event(
            message_id=stream.message_id,
            method="session.output.subscribe",
            stream_id=stream.stream_id,
            event=StreamEvent(
                stream_id=stream.stream_id,
                seq=stream.seq,
                event="snapshot",
                payload=self.session_manager.output_json(stream.session_id, stream.repo_path),
            ),
        ))

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

    async def _publish_peers(self, stream: PeerStream) -> None:
        stream.seq += 1
        await self.send(ProtocolEnvelope.stream_event(
            message_id=stream.message_id,
            method="peer.presence.subscribe",
            stream_id=stream.stream_id,
            event=StreamEvent(
                stream_id=stream.stream_id,
                seq=stream.seq,
                event="snapshot",
                payload={"peers": config_peers_payload(self.config)},
            ),
        ))

    async def _send_file_event(self, stream: FileStream, event: str, payload: dict[str, Any]) -> None:
        await self.send(ProtocolEnvelope.stream_event(
            message_id=stream.message_id,
            method="file.subscribe",
            stream_id=stream.stream_id,
            event=StreamEvent(
                stream_id=stream.stream_id,
                seq=int(payload.get("seq", 0)),
                event=event,
                payload=payload,
            ),
        ))

    async def _send_file_error(self, stream: FileStream, code: str, message: str) -> None:
        await self._send_file_event(stream, "error", {"code": code, "message": message})

    async def _publish_workspace_status(self, stream: WorkspaceStatusStream, *, force: bool) -> bool:
        payload = workspace_status_payload(self.config)
        payload_hash = stable_payload_hash(payload)
        if not force and payload_hash == stream.last_hash:
            return False
        stream.last_hash = payload_hash
        stream.seq += 1
        event = StreamEvent(
            stream_id=stream.stream_id,
            seq=stream.seq,
            event="snapshot",
            payload=payload,
        )
        await self.send(ProtocolEnvelope.stream_event(
            message_id=stream.message_id,
            method="workspace.status.subscribe",
            stream_id=stream.stream_id,
            event=event,
        ))
        return True

    async def _publish_tree(self, stream: TreeStream, *, force: bool) -> bool:
        payload = tree_payload(self.config)
        payload_hash = stable_payload_hash(payload)
        if not force and payload_hash == stream.last_hash:
            return False
        stream.last_hash = payload_hash
        stream.seq += 1
        event = StreamEvent(
            stream_id=stream.stream_id,
            seq=stream.seq,
            event="snapshot",
            payload=payload,
        )
        await self.send(ProtocolEnvelope.stream_event(
            message_id=stream.message_id,
            method="tree.subscribe",
            stream_id=stream.stream_id,
            event=event,
        ))
        return True


def workspace_status_payload(config: ServiceConfig) -> dict[str, Any]:
    return {
        "repos": [repo_status_to_json(repo) for repo in collect_workspace_status(config.workspace.root)],
    }


def tree_payload(config: ServiceConfig) -> dict[str, object]:
    return tree_snapshot_payload(config.workspace.root)


def stable_payload_hash(payload: dict[str, Any] | dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def deps_payload(config: ServiceConfig) -> dict[str, Any]:
    return dependency_graph_to_json(get_dependency_graph(config.workspace.root))


def config_peers_payload(config: ServiceConfig) -> list[dict[str, object]]:
    peers = [self_peer_payload(config)]
    peers.extend(peer_config_to_json(item) for item in config.peers)
    return peers


def peer_health_payload(config: ServiceConfig, payload: dict[str, Any]) -> dict[str, object]:
    peer_id = str(payload.get("peerId", ""))
    if not peer_id:
        raise ValueError("peer.health.get requires peerId")
    for peer in config_peers_payload(config):
        if str(peer.get("id", "")) == peer_id:
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


def self_peer_payload(config: ServiceConfig) -> dict[str, object]:
    probe = build_probe(config)
    capabilities = dict(probe.get("capabilities", {}))
    workspace = dict(probe.get("workspace", {}))
    shells = capabilities.get("shells", [])
    return {
        "id": config.self_peer_id,
        "name": config.self_peer_id,
        "sshAddress": "",
        "location": str(workspace.get("root", config.workspace.root)),
        "os": normalize_peer_os(str(capabilities.get("os", ""))),
        "shells": [Path(str(shell)).name for shell in shells] if isinstance(shells, list) else [],
        "online": True,
        "isSelf": True,
        "status": "online",
        "summary": "Local service is running",
        "lastSeenAt": int(time.time() * 1000),
    }


def peer_config_to_json(value: dict[str, Any]) -> dict[str, object]:
    probe = value.get("probe") if isinstance(value.get("probe"), dict) else {}
    shells = probe.get("shells", []) if isinstance(probe, dict) else []
    online = bool(probe.get("ok", False)) if isinstance(probe, dict) else False
    return {
        "id": str(value.get("peerId", value.get("id", ""))),
        "name": str(value.get("name", value.get("peerId", ""))),
        "sshAddress": str(value.get("sshAddress", "")),
        "location": str(value.get("location", "")),
        "os": normalize_peer_os(str(probe.get("os", ""))) if isinstance(probe, dict) and probe.get("os") else None,
        "shells": [str(shell) for shell in shells] if isinstance(shells, list) else [],
        "online": online,
        "isSelf": False,
        "status": "online" if online else "configured",
        "summary": "Connected" if online else "Configured; not connected",
        "lastSeenAt": None,
    }


def normalize_peer_os(value: str) -> str | None:
    value = value.lower()
    if value.startswith("darwin") or value == "macos":
        return "macos"
    if value.startswith("linux"):
        return "linux"
    if value.startswith(("win", "mingw", "msys", "cygwin")) or value == "windows":
        return "windows"
    return None


def changed_file_to_json(changed: ChangedFile) -> dict[str, object]:
    return {
        "path": changed.path,
        "change": changed.change,
    }


def repo_status_to_json(status: RepoStatus) -> dict[str, object]:
    return {
        "path": status.path,
        "name": status.name,
        "branch": status.branch,
        "head": status.head,
        "ahead": status.ahead,
        "behind": status.behind,
        "dirty": status.dirty,
        "changedFiles": [changed_file_to_json(changed) for changed in status.changed_files],
        **({"error": status.error} if status.error else {}),
    }


def dependency_graph_to_json(graph: DependencyGraph) -> dict[str, object]:
    return {
        "repos": graph.repos,
        "edges": [{"source": edge.source, "target": edge.target} for edge in graph.edges],
        "errors": graph.errors,
    }


class ServiceFileSubscriber:
    def __init__(self, connection: LocalClientConnection, stream: FileStream) -> None:
        self.connection = connection
        self.stream = stream

    async def on_listening(self, resource_id: str) -> None:
        del resource_id

    async def on_stop_listening(self, resource_id: str, reason: str) -> None:
        del resource_id
        if self.stream.stream_id not in self.connection.file_streams:
            return
        await self.connection._send_file_event(self.stream, "closed", {"reason": reason})

    async def on_snapshot(self, snapshot: TextWindowSnapshot) -> None:
        await self.connection._send_file_event(self.stream, "snapshot", text_window_snapshot_to_json(snapshot))

    async def on_delta(self, delta: TextWindowDelta) -> None:
        await self.connection._send_file_event(self.stream, "delta", text_window_delta_to_json(delta))

    async def on_reset(self, reset: ResetEvent) -> None:
        await self.connection._send_file_event(self.stream, "reset", reset_to_json(reset))

    async def on_error(self, code: str, message: str) -> None:
        await self.connection._send_file_error(self.stream, code, message)


def parse_line_window(payload: dict[str, Any]) -> LineWindow:
    window = payload.get("window", payload)
    if not isinstance(window, dict):
        raise ValueError("window must be an object")
    return LineWindow(
        line_start=int(window.get("lineStart", 0)),
        line_end=int(window.get("lineEnd", 400)),
    )


def resolve_file_source(workspace_root: Path, payload: dict[str, Any]) -> dict[str, object]:
    repo_path = str(payload.get("repoPath", ""))
    path = str(payload.get("path", ""))
    ref = str(payload.get("ref", "working"))
    if not path or Path(path).is_absolute() or ".." in Path(path).parts:
        raise ValueError("path must be a workspace-relative file path")
    if Path(repo_path).is_absolute() or ".." in Path(repo_path).parts:
        raise ValueError("repoPath must be relative to the workspace root")
    repo_root = (workspace_root / repo_path).resolve()
    file_path = (repo_root / path).resolve()
    if not file_path.is_relative_to(repo_root):
        raise ValueError("path escapes repo root")
    if ref == "head":
        temp_path = materialize_head_file(repo_root, path)
        return {
            "resource_id": f"{repo_path}::{path}::{ref}",
            "repo_path": repo_path,
            "path": temp_path,
            "ref": ref,
            "temp_path": temp_path,
        }
    if ref != "working":
        raise ValueError(f"unsupported ref: {ref}")
    return {
        "resource_id": f"{repo_path}::{path}::{ref}",
        "repo_path": repo_path,
        "path": file_path,
        "ref": ref,
    }


def materialize_head_file(repo_root: Path, path: str) -> Path:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"HEAD:{path}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip() or f"HEAD does not contain {path}"
        raise ValueError(message)
    handle = tempfile.NamedTemporaryFile(prefix="griplab-head-", delete=False)
    try:
        handle.write(result.stdout)
        return Path(handle.name)
    finally:
        handle.close()


class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, target: Path, notify: Any) -> None:
        self.target = target.resolve()
        self.notify = notify

    def on_any_event(self, event: FileSystemEvent) -> None:
        paths = [Path(event.src_path)]
        dest_path = getattr(event, "dest_path", "")
        if dest_path:
            paths.append(Path(dest_path))
        if any(path.resolve() == self.target for path in paths):
            self.notify()


class FileWatcher:
    def __init__(self, target: Path, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[None]) -> None:
        self.target = target.resolve()
        self.loop = loop
        self.queue = queue
        self.observer = Observer()
        self.handler = FileChangeHandler(self.target, self._notify)
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self.observer.schedule(self.handler, str(self.target.parent), recursive=False)
        self.observer.start()
        self._running = True

    def stop(self) -> None:
        if not self._running:
            return
        self.observer.stop()
        self.observer.join(timeout=2)
        self._running = False

    def _notify(self) -> None:
        self.loop.call_soon_threadsafe(self.queue.put_nowait, None)


@dataclass
class RepoRunState:
    target_id: str
    repo_path: str
    exit_code: int | None
    output: str = ""
    duration_ms: int | None = None
    user_ms: int | None = None
    system_ms: int | None = None


@dataclass
class CommandSessionState:
    id: str
    peer_id: str
    argv: list[str]
    started_at: int
    targets: list[RepoRunState]
    interactive: bool = False
    hidden: bool = False


@dataclass
class TerminalProcess:
    session_id: str
    target: RepoRunState
    master_fd: int
    process: asyncio.subprocess.Process
    read_task: asyncio.Task[None]


def child_cpu_ms() -> tuple[int, int] | None:
    if resource is None:
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return int(usage.ru_utime * 1000), int(usage.ru_stime * 1000)


def elapsed_cpu_ms(start: tuple[int, int] | None) -> tuple[int | None, int | None]:
    end = child_cpu_ms()
    if start is None or end is None:
        return None, None
    return max(0, end[0] - start[0]), max(0, end[1] - start[1])


def format_elapsed_ms(value: int | None) -> str:
    if value is None:
        return "?"
    if value < 1000:
        return f"{value}ms"
    seconds = value / 1000
    return f"{seconds:.1f}s" if seconds < 10 else f"{seconds:.0f}s"


def exit_status_line(target: RepoRunState) -> str:
    if target.exit_code is None:
        return ""
    if target.user_ms is None and target.system_ms is None:
        return f"-- exit status {target.exit_code} wall {format_elapsed_ms(target.duration_ms)} --"
    return (
        f"-- exit status {target.exit_code} "
        f"sys {format_elapsed_ms(target.system_ms)} "
        f"usr {format_elapsed_ms(target.user_ms)} --"
    )


def output_with_exit_status(target: RepoRunState) -> str:
    line = exit_status_line(target)
    if not line:
        return target.output
    prefix = "" if target.output.endswith("\n") or not target.output else "\n"
    return f"{target.output}{prefix}{line}\n"


class SessionManager:
    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self.sessions_root = config.workspace.root / ".grip-lab" / "sessions"
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self.sessions: list[CommandSessionState] = load_sessions(self.sessions_root)
        self.session_subscribers: set[asyncio.Queue[None]] = set()
        self.output_subscribers: dict[tuple[str, str], set[asyncio.Queue[None]]] = {}
        self.terminals: dict[str, TerminalProcess] = {}
        self._index = len(self.sessions)

    def add_sessions_subscriber(self) -> asyncio.Queue[None]:
        queue: asyncio.Queue[None] = asyncio.Queue()
        self.session_subscribers.add(queue)
        return queue

    def remove_sessions_subscriber(self, queue: asyncio.Queue[None]) -> None:
        self.session_subscribers.discard(queue)

    def add_output_subscriber(self, session_id: str, repo_path: str) -> asyncio.Queue[None]:
        queue: asyncio.Queue[None] = asyncio.Queue()
        self.output_subscribers.setdefault((session_id, repo_path), set()).add(queue)
        return queue

    def remove_output_subscriber(self, session_id: str, repo_path: str, queue: asyncio.Queue[None]) -> None:
        subscribers = self.output_subscribers.get((session_id, repo_path))
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self.output_subscribers.pop((session_id, repo_path), None)

    async def run_command(self, payload: dict[str, Any]) -> str:
        argv = parse_argv(payload)
        repos = parse_repo_paths(payload)
        peer_id = str(payload.get("peerId", self.config.self_peer_id))
        self._index += 1
        session_id = f"sess-{int(time.time() * 1000)}-{self._index:04d}"
        session = CommandSessionState(
            id=session_id,
            peer_id=peer_id,
            argv=argv,
            started_at=int(time.time() * 1000),
            targets=[
                RepoRunState(target_id=f"t{index:06d}", repo_path=repo, exit_code=None)
                for index, repo in enumerate(repos, start=1)
            ],
        )
        self.sessions.insert(0, session)
        self._persist_session(session)
        self._append_event(session.id, {"event": "accepted", "sessionId": session.id})
        self._publish_sessions()
        for target in session.targets:
            asyncio.create_task(self._run_target(session, target))
        return session_id

    async def open_terminal(self, payload: dict[str, Any]) -> str:
        argv = parse_terminal_argv(payload)
        repo_path = str(payload.get("repoPath", ""))
        if Path(repo_path).is_absolute() or ".." in Path(repo_path).parts:
            raise ValueError("repoPath must stay within the workspace")
        peer_id = str(payload.get("peerId", self.config.self_peer_id))
        cols = int(payload.get("cols", 120))
        rows = int(payload.get("rows", 30))
        self._index += 1
        session_id = f"term-{int(time.time() * 1000)}-{self._index:04d}"
        target = RepoRunState(target_id="t000001", repo_path=repo_path, exit_code=None)
        session = CommandSessionState(
            id=session_id,
            peer_id=peer_id,
            argv=argv,
            started_at=int(time.time() * 1000),
            targets=[target],
            interactive=True,
        )
        self.sessions.insert(0, session)
        self._persist_session(session)
        self._append_event(session.id, {"event": "terminalOpened", "sessionId": session.id, "targetId": target.target_id})
        master_fd, slave_fd = pty.openpty()
        set_pty_size(master_fd, rows, cols)
        cwd = (self.config.workspace.root / repo_path).resolve()
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")

        def prepare_terminal_child() -> None:
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                env=env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=prepare_terminal_child,
            )
        finally:
            os.close(slave_fd)
        read_task = asyncio.create_task(self._read_terminal(session, target, master_fd))
        self.terminals[session_id] = TerminalProcess(
            session_id=session_id,
            target=target,
            master_fd=master_fd,
            process=process,
            read_task=read_task,
        )
        self._publish_sessions()
        return session_id

    def terminal_input(self, payload: dict[str, Any]) -> bool:
        terminal = self.terminals.get(str(payload.get("sessionId", "")))
        data = payload.get("data")
        if terminal is None or not isinstance(data, str):
            return False
        os.write(terminal.master_fd, data.encode("utf-8"))
        return True

    def terminal_resize(self, payload: dict[str, Any]) -> bool:
        terminal = self.terminals.get(str(payload.get("sessionId", "")))
        if terminal is None:
            return False
        set_pty_size(terminal.master_fd, int(payload.get("rows", 30)), int(payload.get("cols", 120)))
        return True

    async def terminal_close(self, payload: dict[str, Any]) -> bool:
        terminal = self.terminals.get(str(payload.get("sessionId", "")))
        if terminal is None:
            return False
        await self._close_terminal(terminal)
        return True

    def sessions_json(self) -> list[dict[str, object]]:
        return [session_to_json(session) for session in self.sessions]

    def output_json(self, session_id: str, repo_path: str) -> dict[str, object]:
        target = self._find_target(session_id, repo_path)
        return {
            "sessionId": session_id,
            "repoPath": repo_path,
            "output": output_with_exit_status(target) if target else "",
            "exitCode": target.exit_code if target else None,
            "durationMs": target.duration_ms if target else None,
            "userMs": target.user_ms if target else None,
            "systemMs": target.system_ms if target else None,
        }

    def query(self, payload: dict[str, Any]) -> dict[str, object]:
        text = str(payload.get("text", "")).strip().lower()
        peers = set(str(item) for item in payload.get("peers", []) if item)
        repos = set(str(item) for item in payload.get("repos", []) if item is not None)
        statuses = set(str(item) for item in payload.get("status", []) if item)
        include_hidden = bool(payload.get("includeHidden", False))
        limit = max(1, min(500, int(payload.get("limit", 100))))

        matches: list[dict[str, object]] = []
        for session in self.sessions:
            if session.hidden and not include_hidden:
                continue
            if peers and session.peer_id not in peers:
                continue
            status = session_status(session)
            if statuses and status not in statuses:
                continue
            if repos and not any(target.repo_path in repos for target in session.targets):
                continue
            haystack = " ".join(session.argv).lower() + "\n" + "\n".join(target.output.lower() for target in session.targets)
            if text and text not in haystack:
                continue
            matches.append({
                "session": session_to_json(session),
                "status": status,
                "matchedTargets": [
                    target.repo_path
                    for target in session.targets
                    if (not repos or target.repo_path in repos)
                    and (not text or text in target.output.lower() or text in " ".join(session.argv).lower())
                ],
            })
            if len(matches) >= limit:
                break
        return {"matches": matches}

    async def _run_target(self, session: CommandSessionState, target: RepoRunState) -> None:
        start = time.monotonic()
        cpu_start = child_cpu_ms()
        self._append_event(session.id, {
            "event": "targetStarted",
            "sessionId": session.id,
            "targetId": target.target_id,
            "repoPath": target.repo_path,
        })
        self._append_output(session.id, target, "$ " + " ".join(session.argv) + "\n")
        self._publish_output(session.id, target.repo_path)
        cwd = (self.config.workspace.root / target.repo_path).resolve()
        try:
            process = await asyncio.create_subprocess_exec(
                *session.argv,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert process.stdout is not None
            while True:
                chunk = await process.stdout.read(4096)
                if not chunk:
                    break
                self._append_output(session.id, target, chunk.decode("utf-8", errors="replace"))
                self._publish_output(session.id, target.repo_path)
            target.exit_code = await process.wait()
        except Exception as exc:
            self._append_output(session.id, target, f"error: {exc}\n")
            target.exit_code = 127
        finally:
            target.duration_ms = int((time.monotonic() - start) * 1000)
            target.user_ms, target.system_ms = elapsed_cpu_ms(cpu_start)
            self._append_event(session.id, {
                "event": "targetExited",
                "sessionId": session.id,
                "targetId": target.target_id,
                "repoPath": target.repo_path,
                "exitCode": target.exit_code,
                "durationMs": target.duration_ms,
                "userMs": target.user_ms,
                "systemMs": target.system_ms,
            })
            self._persist_session(session)
            self._publish_output(session.id, target.repo_path)
            self._publish_sessions()

    async def _read_terminal(self, session: CommandSessionState, target: RepoRunState, master_fd: int) -> None:
        try:
            while True:
                try:
                    chunk = await asyncio.to_thread(os.read, master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                self._append_output(session.id, target, chunk.decode("utf-8", errors="replace"))
                self._publish_output(session.id, target.repo_path)
        finally:
            terminal = self.terminals.pop(session.id, None)
            if terminal is not None:
                await terminal.process.wait()
                target.exit_code = terminal.process.returncode
                target.duration_ms = int(time.time() * 1000 - session.started_at)
                safe_close_fd(master_fd)
                self._append_event(session.id, {
                    "event": "terminalClosed",
                    "sessionId": session.id,
                    "targetId": target.target_id,
                    "exitCode": target.exit_code,
                    "durationMs": target.duration_ms,
                })
                self._persist_session(session)
                self._publish_output(session.id, target.repo_path)
                self._publish_sessions()

    async def _close_terminal(self, terminal: TerminalProcess) -> None:
        if terminal.process.returncode is None:
            try:
                os.killpg(terminal.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        safe_close_fd(terminal.master_fd)
        try:
            await asyncio.wait_for(terminal.read_task, timeout=2)
        except asyncio.TimeoutError:
            if terminal.process.returncode is None:
                try:
                    os.killpg(terminal.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            terminal.read_task.cancel()
            try:
                await terminal.read_task
            except asyncio.CancelledError:
                pass

    def _find_target(self, session_id: str, repo_path: str) -> RepoRunState | None:
        session = next((item for item in self.sessions if item.id == session_id), None)
        if not session:
            return None
        return next((target for target in session.targets if target.repo_path == repo_path), None)

    def _publish_sessions(self) -> None:
        for queue in list(self.session_subscribers):
            queue.put_nowait(None)

    def _publish_output(self, session_id: str, repo_path: str) -> None:
        for queue in list(self.output_subscribers.get((session_id, repo_path), set())):
            queue.put_nowait(None)

    def _persist_session(self, session: CommandSessionState) -> None:
        session_dir = self._session_dir(session.id)
        session_dir.mkdir(parents=True, exist_ok=True)
        for target in session.targets:
            self._target_dir(session.id, target).mkdir(parents=True, exist_ok=True)
        atomic_write_json(session_dir / "metadata.json", session_to_metadata_json(session))

    def _append_event(self, session_id: str, event: dict[str, object]) -> None:
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        with (session_dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")

    def _append_output(self, session_id: str, target: RepoRunState, text: str) -> None:
        target.output += text
        target_dir = self._target_dir(session_id, target)
        target_dir.mkdir(parents=True, exist_ok=True)
        with (target_dir / "output.log").open("a", encoding="utf-8") as f:
            f.write(text)

    def _session_dir(self, session_id: str) -> Path:
        return self.sessions_root / safe_store_name(session_id)

    def _target_dir(self, session_id: str, target: RepoRunState) -> Path:
        return self._session_dir(session_id) / safe_store_name(target.target_id)


def parse_argv(payload: dict[str, Any]) -> list[str]:
    argv = payload.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
        raise ValueError("cmd.run requires non-empty argv")
    return list(argv)


def parse_repo_paths(payload: dict[str, Any]) -> list[str]:
    repos = payload.get("repos", [""])
    if not isinstance(repos, list) or not repos:
        raise ValueError("cmd.run requires at least one repo")
    result = [str(repo) for repo in repos]
    for repo in result:
        if Path(repo).is_absolute() or ".." in Path(repo).parts:
            raise ValueError("repo paths must stay within the workspace")
    return result


def parse_terminal_argv(payload: dict[str, Any]) -> list[str]:
    argv = payload.get("argv")
    if isinstance(argv, list) and argv and all(isinstance(item, str) and item for item in argv):
        return list(argv)
    shell = os.environ.get("SHELL", "/bin/sh")
    if shell.endswith("sh") and shell != "/bin/sh":
        return [shell, "-l", "-i"]
    return [shell, "-i"]


def session_to_json(session: CommandSessionState) -> dict[str, object]:
    return {
        "id": session.id,
        "peerId": session.peer_id,
        "argv": session.argv,
        "startedAt": session.started_at,
        "interactive": session.interactive,
        "hidden": session.hidden,
        "targets": [
            {
                "targetId": target.target_id,
                "repoPath": target.repo_path,
                "exitCode": target.exit_code,
                "durationMs": target.duration_ms,
                "userMs": target.user_ms,
                "systemMs": target.system_ms,
                "output": output_with_exit_status(target),
            }
            for target in session.targets
        ],
    }


def session_to_metadata_json(session: CommandSessionState) -> dict[str, object]:
    return {
        "id": session.id,
        "peerId": session.peer_id,
        "argv": session.argv,
        "startedAt": session.started_at,
        "interactive": session.interactive,
        "hidden": session.hidden,
        "targets": [
            {
                "targetId": target.target_id,
                "repoPath": target.repo_path,
                "exitCode": target.exit_code,
                "durationMs": target.duration_ms,
                "userMs": target.user_ms,
                "systemMs": target.system_ms,
            }
            for target in session.targets
        ],
    }


def session_status(session: CommandSessionState) -> str:
    exit_codes = [target.exit_code for target in session.targets]
    if any(code is None for code in exit_codes):
        return "running"
    if any(code != 0 for code in exit_codes):
        return "error"
    return "ok"


def load_sessions(root: Path) -> list[CommandSessionState]:
    sessions: list[CommandSessionState] = []
    if not root.exists():
        return sessions
    for session_dir in root.iterdir():
        metadata_path = session_dir / "metadata.json"
        if not metadata_path.is_file():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            sessions.append(session_from_metadata(metadata, session_dir))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
    sessions.sort(key=lambda item: item.started_at, reverse=True)
    return sessions


def session_from_metadata(value: dict[str, Any], session_dir: Path) -> CommandSessionState:
    targets: list[RepoRunState] = []
    for index, target_value in enumerate(value.get("targets", []), start=1):
        target_id = str(target_value.get("targetId", f"t{index:06d}"))
        output_path = session_dir / safe_store_name(target_id) / "output.log"
        try:
            output = output_path.read_text(encoding="utf-8")
        except OSError:
            output = ""
        targets.append(RepoRunState(
            target_id=target_id,
            repo_path=str(target_value.get("repoPath", "")),
            exit_code=target_value.get("exitCode"),
            duration_ms=target_value.get("durationMs"),
            user_ms=target_value.get("userMs"),
            system_ms=target_value.get("systemMs"),
            output=output,
        ))
    session = CommandSessionState(
        id=str(value["id"]),
        peer_id=str(value.get("peerId", "me")),
        argv=[str(item) for item in value.get("argv", [])],
        started_at=int(value.get("startedAt", 0)),
        targets=targets,
        interactive=bool(value.get("interactive", False)),
        hidden=bool(value.get("hidden", False)),
    )
    if session.interactive:
        for target in session.targets:
            if target.exit_code is None:
                target.exit_code = -1
                if target.output and not target.output.endswith("\n"):
                    target.output += "\n"
                target.output += "[terminal session is no longer attached]\n"
    return session


def atomic_write_json(path: Path, value: dict[str, object]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def safe_store_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value) or "_"


def is_closing_transport_error(exc: RuntimeError) -> bool:
    message = str(exc).lower()
    return "closing transport" in message or "closed transport" in message or "write_eof" in message


def set_pty_size(fd: int, rows: int, cols: int) -> None:
    rows = max(1, rows)
    cols = max(1, cols)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def safe_close_fd(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass

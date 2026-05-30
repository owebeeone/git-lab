"""aiohttp local client app for health, probe, and service protocol streams."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web
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
from griplab_service.config import ServiceConfig
from griplab_service.local_client.deps import DependencyGraph, get_dependency_graph
from griplab_service.local_client.tree import TreeWatcher, tree_snapshot_payload
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

CONFIG_KEY = web.AppKey("config", ServiceConfig)
SESSIONS_KEY = web.AppKey("sessions", Any)


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
    app.router.add_get("/health", handle_health)
    app.router.add_get("/probe", handle_probe)
    app.router.add_get("/workspace/status", handle_workspace_status)
    app.router.add_get("/deps", handle_deps)
    app.router.add_get("/ws", handle_ws)
    return app


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
    connection = LocalClientConnection(config, request.app[SESSIONS_KEY], ws)

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
    watcher: TreeWatcher | None = None


@dataclass
class FileStream:
    message_id: str
    stream_id: str
    connection: FileConnection | None = None
    subscription: Any | None = None
    task: asyncio.Task[None] | None = None
    watcher: "FileWatcher" | None = None
    queue: asyncio.Queue[None] | None = None


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


class LocalClientConnection:
    def __init__(self, config: ServiceConfig, session_manager: "SessionManager", ws: web.WebSocketResponse) -> None:
        self.config = config
        self.session_manager = session_manager
        self.ws = ws
        self.workspace_status_streams: dict[str, WorkspaceStatusStream] = {}
        self.tree_streams: dict[str, TreeStream] = {}
        self.file_streams: dict[str, FileStream] = {}
        self.sessions_streams: dict[str, SessionsStream] = {}
        self.output_streams: dict[str, SessionOutputStream] = {}
        self._send_lock = asyncio.Lock()

    async def send(self, envelope: ProtocolEnvelope) -> None:
        async with self._send_lock:
            await self.ws.send_json(envelope_to_json(envelope))

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
        watcher = TreeWatcher(self.config.workspace.root, asyncio.get_running_loop(), queue)
        stream.watcher = watcher
        self.tree_streams[stream_id] = stream
        await self._publish_tree(stream, force=True)
        watcher.start()
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
            if source["ref"] != "working":
                await self._send_file_error(stream, "unsupported-ref", "only working-tree file streams are available")
                return
            window = parse_line_window(payload)
            queue: asyncio.Queue[None] = asyncio.Queue()
            stream.queue = queue
            subscriber = ServiceFileSubscriber(self, stream)
            connection = FileConnection(str(source["resource_id"]), source["path"])
            stream.connection = connection
            await connection.open()
            stream.subscription = await connection.subscribe_window(subscriber, window)
            watcher = FileWatcher(Path(source["path"]), asyncio.get_running_loop(), queue)
            stream.watcher = watcher
            watcher.start()
            stream.task = asyncio.create_task(self._watch_file(stream))
        except Exception as exc:
            await self._send_file_error(stream, "file-open-failed", str(exc))

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

    async def close(self) -> None:
        status_tasks = [stream.task for stream in self.workspace_status_streams.values() if stream.task is not None]
        tree_streams = list(self.tree_streams.values())
        file_streams = list(self.file_streams.values())
        sessions_streams = list(self.sessions_streams.values())
        output_streams = list(self.output_streams.values())
        self.workspace_status_streams.clear()
        self.tree_streams.clear()
        self.file_streams.clear()
        self.sessions_streams.clear()
        self.output_streams.clear()
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
        tasks = status_tasks + [stream.task for stream in sessions_streams + output_streams if stream.task is not None]
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
                await stream.queue.get()
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
        if stream.watcher is not None:
            stream.watcher.stop()

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
    return {
        "resource_id": f"{repo_path}::{path}::{ref}",
        "repo_path": repo_path,
        "path": file_path,
        "ref": ref,
    }


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
    repo_path: str
    exit_code: int | None
    output: str = ""
    duration_ms: int | None = None


@dataclass
class CommandSessionState:
    id: str
    peer_id: str
    argv: list[str]
    started_at: int
    targets: list[RepoRunState]
    interactive: bool = False
    hidden: bool = False


class SessionManager:
    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self.sessions: list[CommandSessionState] = []
        self.session_subscribers: set[asyncio.Queue[None]] = set()
        self.output_subscribers: dict[tuple[str, str], set[asyncio.Queue[None]]] = {}
        self._index = 0

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
            targets=[RepoRunState(repo_path=repo, exit_code=None) for repo in repos],
        )
        self.sessions.insert(0, session)
        self._publish_sessions()
        for target in session.targets:
            asyncio.create_task(self._run_target(session, target))
        return session_id

    def sessions_json(self) -> list[dict[str, object]]:
        return [session_to_json(session) for session in self.sessions]

    def output_json(self, session_id: str, repo_path: str) -> dict[str, object]:
        target = self._find_target(session_id, repo_path)
        return {
            "sessionId": session_id,
            "repoPath": repo_path,
            "output": target.output if target else "",
            "exitCode": target.exit_code if target else None,
        }

    async def _run_target(self, session: CommandSessionState, target: RepoRunState) -> None:
        start = time.monotonic()
        target.output += "$ " + " ".join(session.argv) + "\n"
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
                target.output += chunk.decode("utf-8", errors="replace")
                self._publish_output(session.id, target.repo_path)
            target.exit_code = await process.wait()
        except Exception as exc:
            target.output += f"error: {exc}\n"
            target.exit_code = 127
        finally:
            target.duration_ms = int((time.monotonic() - start) * 1000)
            self._publish_output(session.id, target.repo_path)
            self._publish_sessions()

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
                "repoPath": target.repo_path,
                "exitCode": target.exit_code,
                "durationMs": target.duration_ms,
                "output": target.output,
            }
            for target in session.targets
        ],
    }

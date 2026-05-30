"""aiohttp local client app for health, probe, and service protocol streams."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from aiohttp import WSMsgType, web

from griplab_service.config import ServiceConfig
from griplab_service.local_client.deps import DependencyGraph, get_dependency_graph
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

    async for msg in ws:
        if msg.type != WSMsgType.TEXT:
            continue
        try:
            envelope = envelope_from_json(json.loads(msg.data))
            response = handle_protocol_message(config, envelope)
        except (json.JSONDecodeError, KeyError, ProtocolValidationError, ValueError) as exc:
            response = ProtocolEnvelope.error_response(
                message_id="invalid",
                method=None,
                error=ErrorInfo("bad-message", str(exc)),
            )
        if isinstance(response, list):
            for item in response:
                await ws.send_json(envelope_to_json(item))
        else:
            await ws.send_json(envelope_to_json(response))

    return ws


def handle_protocol_message(
    config: ServiceConfig,
    envelope: ProtocolEnvelope,
) -> ProtocolEnvelope | list[ProtocolEnvelope]:
    if envelope.kind != "request":
        return ProtocolEnvelope.error_response(
            message_id=envelope.message_id,
            method=envelope.method,
            error=ErrorInfo("bad-kind", "only request envelopes are accepted by the local client"),
        )
    if envelope.method == "deps.get":
        return ProtocolEnvelope.response(
            message_id=envelope.message_id,
            method=envelope.method,
            payload=deps_payload(config),
        )
    if envelope.method == "workspace.status.subscribe":
        if not envelope.stream_id:
            return ProtocolEnvelope.error_response(
                message_id=envelope.message_id,
                method=envelope.method,
                error=ErrorInfo("missing-stream-id", "workspace.status.subscribe requires streamId"),
            )
        event = StreamEvent(
            stream_id=envelope.stream_id,
            seq=1,
            event="snapshot",
            payload=workspace_status_payload(config),
        )
        return [
            ProtocolEnvelope.stream_event(
                message_id=envelope.message_id,
                method=envelope.method,
                stream_id=envelope.stream_id,
                event=event,
            )
        ]
    return ProtocolEnvelope.error_response(
        message_id=envelope.message_id,
        method=envelope.method,
        error=ErrorInfo("unknown-method", f"unknown method: {envelope.method}"),
    )


def workspace_status_payload(config: ServiceConfig) -> dict[str, Any]:
    return {
        "repos": [repo_status_to_json(repo) for repo in collect_workspace_status(config.workspace.root)],
    }


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

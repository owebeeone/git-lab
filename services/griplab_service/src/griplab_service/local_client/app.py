"""Dependency-free local client health/probe server."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from griplab_service.config import ServiceConfig
from griplab_service.local_client.deps import DependencyGraph, get_dependency_graph
from griplab_service.local_client.workspace import ChangedFile, RepoStatus, collect_workspace_status
from griplab_service.probe import build_probe


class LocalClientServer:
    """Small stdlib HTTP server for phase-1 health and probe checks."""

    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        handler = self._make_handler(config)
        self._server = ThreadingHTTPServer((config.listen.host, config.listen.port), handler)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def serve_forever(self) -> None:
        self._server.serve_forever()

    @staticmethod
    def _make_handler(config: ServiceConfig) -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/health":
                    self._write_json({"ok": True, "mode": config.mode})
                    return
                if self.path == "/probe":
                    self._write_json(build_probe(config))
                    return
                if self.path == "/workspace/status":
                    self._write_json({
                        "repos": [repo_status_to_json(repo) for repo in collect_workspace_status(config.workspace.root)],
                    })
                    return
                if self.path == "/deps":
                    self._write_json(dependency_graph_to_json(get_dependency_graph(config.workspace.root)))
                    return
                self.send_error(404, "not found")

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _write_json(self, value: dict[str, object]) -> None:
                body = json.dumps(value, sort_keys=True).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


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

"""Dependency-free local client health/probe server."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from griplab_service.config import ServiceConfig
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

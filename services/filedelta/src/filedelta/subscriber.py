"""Subscriber callback protocol for async filedelta streams."""

from __future__ import annotations

from typing import Protocol

from .model import ResetEvent, TextWindowDelta, TextWindowSnapshot


class FileSubscriber(Protocol):
    async def on_listening(self, resource_id: str) -> None: ...

    async def on_stop_listening(self, resource_id: str, reason: str) -> None: ...

    async def on_snapshot(self, snapshot: TextWindowSnapshot) -> None: ...

    async def on_delta(self, delta: TextWindowDelta) -> None: ...

    async def on_reset(self, reset: ResetEvent) -> None: ...

    async def on_error(self, code: str, message: str) -> None: ...

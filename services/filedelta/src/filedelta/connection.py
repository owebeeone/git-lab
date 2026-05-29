"""Async file connection runtime for pure filedelta streams."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .model import LineWindow
from .subscriber import FileSubscriber
from .window import FileWindowSubscription


class FileConnection:
    """Owns one source file and its active window subscriptions."""

    def __init__(self, resource_id: str, path: Path | str) -> None:
        if not resource_id:
            raise ValueError("resource_id must not be empty")
        self.resource_id = resource_id
        self.path = Path(path)
        self.file_version_index = 1
        self.file_version = self._format_file_version()
        self._subscriptions: list[FileWindowSubscription] = []
        self._window_id_index = 0
        self._closed = False

    async def open(self) -> None:
        await self.read_bytes()
        self._closed = False

    async def close(self, reason: str = "closed") -> None:
        if self._closed:
            return
        self._closed = True
        for subscription in list(self._subscriptions):
            await subscription.close(reason)
        self._subscriptions.clear()

    async def subscribe_window(
        self,
        subscriber: FileSubscriber,
        window: LineWindow,
    ) -> FileWindowSubscription:
        if self._closed:
            raise RuntimeError("connection is closed")
        self._window_id_index += 1
        subscription = FileWindowSubscription(
            self,
            subscriber,
            window,
            f"{self.resource_id}:window:{self._window_id_index:06d}",
        )
        self._subscriptions.append(subscription)
        await subscription.open()
        return subscription

    async def file_changed(self, reason: str = "file-change") -> None:
        if self._closed:
            return
        try:
            await self.read_bytes()
        except FileNotFoundError:
            for subscription in list(self._subscriptions):
                await subscription.deleted()
            self._subscriptions.clear()
            return

        self.file_version_index += 1
        self.file_version = self._format_file_version()
        for subscription in list(self._subscriptions):
            await subscription.file_changed(reason)

    async def read_bytes(self) -> bytes:
        return await asyncio.to_thread(self.path.read_bytes)

    def remove_subscription(self, subscription: FileWindowSubscription) -> None:
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)

    def _format_file_version(self) -> str:
        return f"fv{self.file_version_index:06d}"

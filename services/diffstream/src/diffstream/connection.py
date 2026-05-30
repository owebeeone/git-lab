"""Async diff orchestration over abstract source streams."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from .algorithm import build_diff_payload, effective_window
from .model import (
    DIFF_CONTENT_TYPE,
    DiffDiagnostic,
    DiffEndpoint,
    DiffPayload,
    DiffSourceState,
    DiffWindow,
    format_diff_id,
    format_diff_version,
)

SourceSide = Literal["left", "right"]


@dataclass(frozen=True)
class DiffConnectionKey:
    """Stable sharing key for one synthetic diff connection."""

    left: DiffEndpoint
    right: DiffEndpoint
    window: DiffWindow
    context_lines: int
    content_type: str = DIFF_CONTENT_TYPE


@dataclass(frozen=True)
class SourceSnapshot:
    """Latest decoded text-window source state for one endpoint."""

    file_version: str
    content_hash: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class SourceReset:
    """Source stream reset notification."""

    reason: str


@dataclass(frozen=True)
class SourceFailure:
    """Non-fatal source problem that should become a diff diagnostic."""

    code: str
    message: str
    details: dict[str, object] | None = None


SourceEvent = SourceSnapshot | SourceReset | SourceFailure


@dataclass(frozen=True)
class DiffStreamEvent:
    """Event emitted by a synthetic diff connection subscriber."""

    seq: int
    event: str
    payload: DiffPayload


class SourceSubscription(Protocol):
    """Abstract source subscription consumed by DiffConnection."""

    def __aiter__(self) -> AsyncIterator[SourceEvent]:
        ...

    async def close(self) -> None:
        ...


SourceOpener = Callable[[SourceSide, DiffEndpoint, DiffWindow], Awaitable[SourceSubscription]]


class DiffSubscriber:
    """One ref-counted subscriber to a DiffConnection."""

    def __init__(self, connection: DiffConnection, subscriber_id: int, queue: asyncio.Queue[DiffStreamEvent | None]):
        self._connection = connection
        self._subscriber_id = subscriber_id
        self._queue = queue
        self._closed = False

    def __aiter__(self) -> DiffSubscriber:
        return self

    async def __anext__(self) -> DiffStreamEvent:
        event = await self._queue.get()
        if event is None:
            raise StopAsyncIteration
        return event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._connection._remove_subscriber(self._subscriber_id)


class DiffConnection:
    """Ref-counted synthetic diff stream over two source streams."""

    def __init__(
        self,
        *,
        key: DiffConnectionKey,
        source_opener: SourceOpener,
        diff_id: str = format_diff_id(1),
        debounce_seconds: float = 0.016,
    ) -> None:
        self.key = key
        self._source_opener = source_opener
        self._diff_id = diff_id
        self._debounce_seconds = debounce_seconds
        self._subscribers: dict[int, asyncio.Queue[DiffStreamEvent | None]] = {}
        self._next_subscriber_id = 1
        self._seq = 0
        self._version = 0
        self._left_snapshot: SourceSnapshot | None = None
        self._right_snapshot: SourceSnapshot | None = None
        self._subscriptions: dict[SourceSide, SourceSubscription] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False
        self._closed = False
        self._dirty_handle: asyncio.TimerHandle | None = None
        self._lock = asyncio.Lock()

    async def subscribe(self) -> DiffSubscriber:
        async with self._lock:
            if self._closed:
                raise RuntimeError("diff connection is closed")
            queue: asyncio.Queue[DiffStreamEvent | None] = asyncio.Queue()
            subscriber_id = self._next_subscriber_id
            self._next_subscriber_id += 1
            self._subscribers[subscriber_id] = queue
            if not self._started:
                await self._start()
        return DiffSubscriber(self, subscriber_id, queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def _start(self) -> None:
        read_window = effective_window(self.key.window, self.key.context_lines)
        left = await self._source_opener("left", self.key.left, read_window)
        right = await self._source_opener("right", self.key.right, read_window)
        self._subscriptions = {"left": left, "right": right}
        self._tasks = [
            asyncio.create_task(self._consume_source("left", left)),
            asyncio.create_task(self._consume_source("right", right)),
        ]
        self._started = True

    async def _consume_source(self, side: SourceSide, source: SourceSubscription) -> None:
        try:
            async for event in source:
                await self._apply_source_event(side, event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._publish_diagnostic(
                "peer-offline",
                f"{side} source stream failed: {exc}",
                side,
                {"exception": type(exc).__name__},
            )

    async def _apply_source_event(self, side: SourceSide, event: SourceEvent) -> None:
        if isinstance(event, SourceSnapshot):
            async with self._lock:
                if side == "left":
                    self._left_snapshot = event
                else:
                    self._right_snapshot = event
                self._schedule_recompute_locked()
        elif isinstance(event, SourceReset):
            async with self._lock:
                if side == "left":
                    self._left_snapshot = None
                else:
                    self._right_snapshot = None
            await self._publish_diagnostic(
                "peer-offline",
                f"{side} source reset: {event.reason}",
                side,
                {"reason": event.reason},
            )
        elif isinstance(event, SourceFailure):
            async with self._lock:
                if side == "left":
                    self._left_snapshot = None
                else:
                    self._right_snapshot = None
            await self._publish_diagnostic(event.code, event.message, side, event.details or {})

    def _schedule_recompute_locked(self) -> None:
        if self._left_snapshot is None or self._right_snapshot is None:
            return
        if self._dirty_handle is not None:
            return
        loop = asyncio.get_running_loop()
        self._dirty_handle = loop.call_later(
            self._debounce_seconds,
            lambda: asyncio.create_task(self._recompute_if_ready()),
        )

    async def _recompute_if_ready(self) -> None:
        async with self._lock:
            self._dirty_handle = None
            if self._left_snapshot is None or self._right_snapshot is None:
                return
            self._version += 1
            payload = build_diff_payload(
                diff_id=self._diff_id,
                version=format_diff_version(self._version),
                left=self._source_state("left", self._left_snapshot),
                right=self._source_state("right", self._right_snapshot),
                window=self.key.window,
                left_lines=self._left_snapshot.lines,
                right_lines=self._right_snapshot.lines,
                context_lines=self.key.context_lines,
            )
            event = self._next_event("snapshot", payload)
            self._publish_locked(event)

    async def _publish_diagnostic(
        self,
        code: str,
        message: str,
        side: SourceSide,
        details: dict[str, object],
    ) -> None:
        async with self._lock:
            self._version += 1
            payload = DiffPayload(
                diff_id=self._diff_id,
                version=format_diff_version(self._version),
                left=self._source_state("left", self._left_snapshot),
                right=self._source_state("right", self._right_snapshot),
                window=self.key.window,
                hunks=[],
                diagnostics=[
                    DiffDiagnostic(
                        code=code,
                        message=message,
                        endpoint=side,
                        details=details,
                    )
                ],
            )
            payload.validate()
            event = self._next_event("snapshot", payload)
            self._publish_locked(event)

    def _source_state(self, side: SourceSide, snapshot: SourceSnapshot | None) -> DiffSourceState:
        endpoint = self.key.left if side == "left" else self.key.right
        if snapshot is None:
            return DiffSourceState(endpoint, "fv000000", "sha256:unavailable")
        return DiffSourceState(endpoint, snapshot.file_version, snapshot.content_hash)

    def _next_event(self, event: str, payload: DiffPayload) -> DiffStreamEvent:
        self._seq += 1
        return DiffStreamEvent(seq=self._seq, event=event, payload=payload)

    def _publish_locked(self, event: DiffStreamEvent) -> None:
        for queue in self._subscribers.values():
            queue.put_nowait(event)

    async def _remove_subscriber(self, subscriber_id: int) -> None:
        async with self._lock:
            queue = self._subscribers.pop(subscriber_id, None)
            if queue is not None:
                queue.put_nowait(None)
            if not self._subscribers:
                await self._close_locked()

    async def _close_locked(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._dirty_handle is not None:
            self._dirty_handle.cancel()
            self._dirty_handle = None
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        for subscription in self._subscriptions.values():
            await subscription.close()
        self._subscriptions.clear()
        for queue in self._subscribers.values():
            queue.put_nowait(None)
        self._subscribers.clear()

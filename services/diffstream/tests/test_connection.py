from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from diffstream import (
    DiffConnection,
    DiffConnectionKey,
    DiffEndpoint,
    DiffRef,
    DiffStreamEvent,
    DiffWindow,
    SourceFailure,
    SourceReset,
    SourceSnapshot,
)


class FakeSource:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[object] = asyncio.Queue()
        self.closed = False

    def __aiter__(self) -> AsyncIterator[object]:
        return self

    async def __anext__(self) -> object:
        event = await self.queue.get()
        if event is None:
            raise StopAsyncIteration
        return event

    async def close(self) -> None:
        self.closed = True
        self.queue.put_nowait(None)

    def emit(self, event: object) -> None:
        self.queue.put_nowait(event)


def endpoint(peer_id: str = "left") -> DiffEndpoint:
    return DiffEndpoint(peer_id, "", "src/app.ts", DiffRef("working"))


async def make_connection(debounce_seconds: float = 0.001) -> tuple[DiffConnection, dict[str, FakeSource], dict[str, DiffWindow]]:
    sources: dict[str, FakeSource] = {}
    windows: dict[str, DiffWindow] = {}

    async def opener(side: str, _endpoint: DiffEndpoint, window: DiffWindow) -> FakeSource:
        source = FakeSource()
        sources[side] = source
        windows[side] = window
        return source

    connection = DiffConnection(
        key=DiffConnectionKey(
            left=endpoint("left"),
            right=endpoint("right"),
            window=DiffWindow(2, 5),
            context_lines=2,
        ),
        source_opener=opener,
        debounce_seconds=debounce_seconds,
    )
    return connection, sources, windows


async def next_event(subscriber) -> DiffStreamEvent:
    return await asyncio.wait_for(subscriber.__anext__(), timeout=0.5)


def snapshot(version: int, *lines: str) -> SourceSnapshot:
    return SourceSnapshot(
        file_version=f"fv00000{version}",
        content_hash=f"sha256:{version}",
        lines=tuple(lines),
    )


def test_subscribe_opens_effective_source_windows() -> None:
    async def run() -> None:
        connection, sources, windows = await make_connection()
        subscriber = await connection.subscribe()

        assert set(sources) == {"left", "right"}
        assert windows["left"] == DiffWindow(0, 7)
        assert windows["right"] == DiffWindow(0, 7)

        await subscriber.close()

    asyncio.run(run())


def test_left_and_right_snapshots_publish_ordered_diff_snapshot() -> None:
    async def run() -> None:
        connection, sources, _windows = await make_connection()
        subscriber = await connection.subscribe()
        sources["left"].emit(snapshot(1, "a", "old"))
        sources["right"].emit(snapshot(2, "a", "new"))

        event = await next_event(subscriber)

        assert event.seq == 1
        assert event.event == "snapshot"
        assert event.payload.version == "dv000001"
        assert event.payload.hunks[0].lines[1].kind == "change"
        assert event.payload.left.file_version == "fv000001"
        assert event.payload.right.file_version == "fv000002"

        await subscriber.close()

    asyncio.run(run())


def test_update_on_either_side_recomputes() -> None:
    async def run() -> None:
        connection, sources, _windows = await make_connection()
        subscriber = await connection.subscribe()
        sources["left"].emit(snapshot(1, "a"))
        sources["right"].emit(snapshot(2, "b"))
        await next_event(subscriber)

        sources["right"].emit(snapshot(3, "a"))
        event = await next_event(subscriber)

        assert event.seq == 2
        assert event.payload.version == "dv000002"
        assert event.payload.hunks == []
        assert event.payload.right.file_version == "fv000003"

        await subscriber.close()

    asyncio.run(run())


def test_concurrent_updates_coalesce_into_one_snapshot() -> None:
    async def run() -> None:
        connection, sources, _windows = await make_connection(debounce_seconds=0.01)
        subscriber = await connection.subscribe()
        sources["left"].emit(snapshot(1, "a"))
        sources["right"].emit(snapshot(2, "b"))
        await next_event(subscriber)

        sources["left"].emit(snapshot(3, "same"))
        sources["right"].emit(snapshot(4, "same"))
        event = await next_event(subscriber)

        assert event.seq == 2
        assert event.payload.left.file_version == "fv000003"
        assert event.payload.right.file_version == "fv000004"
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(subscriber.__anext__(), timeout=0.03)

        await subscriber.close()

    asyncio.run(run())


def test_source_failure_publishes_structured_diagnostic() -> None:
    async def run() -> None:
        connection, sources, _windows = await make_connection()
        subscriber = await connection.subscribe()

        sources["right"].emit(SourceFailure("missing-file", "right file missing", {"path": "src/app.ts"}))
        event = await next_event(subscriber)

        assert event.payload.hunks == []
        assert event.payload.diagnostics[0].code == "missing-file"
        assert event.payload.diagnostics[0].endpoint == "right"

        await subscriber.close()

    asyncio.run(run())


def test_source_reset_publishes_diagnostic_then_fresh_snapshot_can_recompute() -> None:
    async def run() -> None:
        connection, sources, _windows = await make_connection()
        subscriber = await connection.subscribe()
        sources["left"].emit(snapshot(1, "a"))
        sources["right"].emit(snapshot(2, "b"))
        await next_event(subscriber)

        sources["left"].emit(SourceReset("file-changed"))
        reset_event = await next_event(subscriber)
        assert reset_event.payload.diagnostics[0].code == "peer-offline"

        sources["left"].emit(snapshot(3, "b"))
        event = await next_event(subscriber)
        assert event.payload.version == "dv000003"
        assert event.payload.hunks == []

        await subscriber.close()

    asyncio.run(run())


def test_ref_count_closes_sources_after_last_subscriber() -> None:
    async def run() -> None:
        connection, sources, _windows = await make_connection()
        first = await connection.subscribe()
        second = await connection.subscribe()

        assert connection.subscriber_count == 2
        await first.close()
        assert connection.subscriber_count == 1
        assert not sources["left"].closed
        assert not sources["right"].closed

        await second.close()
        assert connection.subscriber_count == 0
        assert sources["left"].closed
        assert sources["right"].closed

    asyncio.run(run())

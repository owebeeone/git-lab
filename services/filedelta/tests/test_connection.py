from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from filedelta import FileConnection, LineWindow


class RecordingSubscriber:
    def __init__(self, *, fail_on_delta: bool = False) -> None:
        self.events: list[tuple[str, object]] = []
        self.fail_on_delta = fail_on_delta

    async def on_listening(self, resource_id: str) -> None:
        self.events.append(("listening", resource_id))

    async def on_stop_listening(self, resource_id: str, reason: str) -> None:
        self.events.append(("stop", (resource_id, reason)))

    async def on_snapshot(self, snapshot) -> None:
        self.events.append(("snapshot", snapshot))

    async def on_delta(self, delta) -> None:
        if self.fail_on_delta:
            raise RuntimeError("consumer failed")
        self.events.append(("delta", delta))

    async def on_reset(self, reset) -> None:
        self.events.append(("reset", reset))

    async def on_error(self, code: str, message: str) -> None:
        self.events.append(("error", (code, message)))

    def names(self) -> list[str]:
        return [name for name, _value in self.events]


class FileConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sample.txt"
        self.path.write_bytes(b"alpha\nbeta\ngamma\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_open_emits_snapshot(self) -> None:
        connection = FileConnection("file:sample", self.path)
        await connection.open()
        subscriber = RecordingSubscriber()
        await connection.subscribe_window(subscriber, LineWindow(0, 2))
        self.assertEqual(subscriber.names(), ["listening", "snapshot"])
        snapshot = subscriber.events[-1][1]
        self.assertEqual(snapshot.data, b"alpha\nbeta\n")

    async def test_file_changed_emits_delta(self) -> None:
        connection = FileConnection("file:sample", self.path)
        await connection.open()
        subscriber = RecordingSubscriber()
        subscription = await connection.subscribe_window(subscriber, LineWindow(0, 2))
        self.path.write_bytes(b"alpha\nBETA\ngamma\n")
        await connection.file_changed()
        self.assertIn("delta", subscriber.names())
        self.assertEqual(subscription.snapshot.data, b"alpha\nBETA\n")

    async def test_update_window_grows_without_file_change(self) -> None:
        connection = FileConnection("file:sample", self.path)
        await connection.open()
        subscriber = RecordingSubscriber()
        subscription = await connection.subscribe_window(subscriber, LineWindow(1, 2))
        await subscription.update_window(LineWindow(0, 3))
        self.assertEqual(subscription.snapshot.file_version, "fv000001")
        self.assertEqual(subscription.snapshot.data, b"alpha\nbeta\ngamma\n")

    async def test_two_subscribers_keep_independent_sequences(self) -> None:
        connection = FileConnection("file:sample", self.path)
        await connection.open()
        first = RecordingSubscriber()
        second = RecordingSubscriber()
        first_subscription = await connection.subscribe_window(first, LineWindow(0, 1))
        second_subscription = await connection.subscribe_window(second, LineWindow(1, 2))
        self.path.write_bytes(b"ALPHA\nbeta\ngamma\n")
        await connection.file_changed()
        self.assertEqual(first_subscription.seq, 1)
        self.assertEqual(second_subscription.seq, 1)
        self.assertEqual(first_subscription.snapshot.window_version, "wv000002")
        self.assertEqual(second_subscription.snapshot.window_version, "wv000002")

    async def test_close_emits_stop(self) -> None:
        connection = FileConnection("file:sample", self.path)
        await connection.open()
        subscriber = RecordingSubscriber()
        await connection.subscribe_window(subscriber, LineWindow(0, 1))
        await connection.close("done")
        self.assertEqual(subscriber.events[-1], ("stop", ("file:sample", "done")))

    async def test_deleted_file_emits_error_and_closes(self) -> None:
        connection = FileConnection("file:sample", self.path)
        await connection.open()
        subscriber = RecordingSubscriber()
        subscription = await connection.subscribe_window(subscriber, LineWindow(0, 1))
        self.path.unlink()
        await connection.file_changed()
        self.assertTrue(subscription.closed)
        self.assertIn("error", subscriber.names())
        self.assertEqual(subscriber.events[-1], ("stop", ("file:sample", "deleted")))

    async def test_consumer_failure_closes_subscription(self) -> None:
        connection = FileConnection("file:sample", self.path)
        await connection.open()
        subscriber = RecordingSubscriber(fail_on_delta=True)
        subscription = await connection.subscribe_window(subscriber, LineWindow(0, 1))
        self.path.write_bytes(b"ALPHA\nbeta\ngamma\n")
        with self.assertRaises(RuntimeError):
            await connection.file_changed()
        self.assertTrue(subscription.closed)
        self.assertEqual(subscriber.events[-1], ("stop", ("file:sample", "consumer-error")))


if __name__ == "__main__":
    unittest.main()

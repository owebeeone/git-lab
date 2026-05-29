from __future__ import annotations

import unittest

from filedelta import (
    LineWindow,
    ResetEvent,
    TextWindowDelta,
    TextWindowSnapshot,
    make_reset,
    make_text_window_snapshot,
    make_text_window_update,
)


class JsonCodecTests(unittest.TestCase):
    def test_text_window_snapshot_round_trips(self) -> None:
        snapshot = make_text_window_snapshot(
            "file:json",
            "win:json",
            b"alpha\nbeta\n",
            LineWindow(0, 2),
            file_version="fv000001",
            window_version="wv000001",
        )
        parsed = TextWindowSnapshot.from_json_dict(snapshot.to_json_dict())
        self.assertEqual(parsed, snapshot)

    def test_text_window_delta_round_trips(self) -> None:
        snapshot = make_text_window_snapshot(
            "file:json",
            "win:json",
            b"alpha\nbeta\n",
            LineWindow(0, 2),
            file_version="fv000001",
            window_version="wv000001",
        )
        delta = make_text_window_update(
            snapshot,
            b"alpha\nBETA\n",
            LineWindow(0, 2),
            seq=1,
            result_file_version="fv000002",
            result_window_version="wv000002",
        )
        self.assertIsInstance(delta, TextWindowDelta)
        assert isinstance(delta, TextWindowDelta)
        parsed = TextWindowDelta.from_json_dict(delta.to_json_dict())
        self.assertEqual(parsed, delta)

    def test_reset_round_trips(self) -> None:
        snapshot = make_text_window_snapshot(
            "file:json",
            "win:json",
            b"alpha\nbeta\n",
            LineWindow(1, 2),
            file_version="fv000002",
            window_version="wv000002",
        )
        reset = make_reset("window-move", 1, snapshot)
        parsed = ResetEvent.from_json_dict(reset.to_json_dict())
        self.assertEqual(parsed, reset)


if __name__ == "__main__":
    unittest.main()

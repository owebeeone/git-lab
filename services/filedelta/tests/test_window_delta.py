from __future__ import annotations

import random
import unittest
from dataclasses import replace

from filedelta import (
    LineWindow,
    ResetEvent,
    TextWindowDelta,
    apply_text_window_delta,
    make_text_window_snapshot,
    make_text_window_update,
)
from filedelta.errors import DeltaApplyError


def _snapshot(data: bytes, window: LineWindow, *, fv: str = "fv000001", wv: str = "wv000001"):
    return make_text_window_snapshot(
        "file:window",
        "win:window",
        data,
        window,
        file_version=fv,
        window_version=wv,
    )


def _apply_update(old, new_data: bytes, window: LineWindow, *, reason: str | None = None):
    event = make_text_window_update(
        old,
        new_data,
        window,
        seq=1,
        result_file_version="fv000002",
        result_window_version="wv000002",
        reason=reason,
    )
    if isinstance(event, ResetEvent):
        return event.snapshot
    return apply_text_window_delta(old, event)


class WindowDeltaTests(unittest.TestCase):
    def test_grow_at_end(self) -> None:
        data = b"alpha\nbeta\ngamma\n"
        base = _snapshot(data, LineWindow(0, 1))
        event = make_text_window_update(
            base,
            data,
            LineWindow(0, 2),
            seq=1,
            result_file_version="fv000001",
            result_window_version="wv000002",
        )
        self.assertIsInstance(event, TextWindowDelta)
        updated = apply_text_window_delta(base, event)
        self.assertEqual(updated.data, b"alpha\nbeta\n")

    def test_grow_at_beginning(self) -> None:
        data = b"alpha\nbeta\ngamma\n"
        base = _snapshot(data, LineWindow(1, 2))
        updated = _apply_update(base, data, LineWindow(0, 2))
        self.assertEqual(updated.data, b"alpha\nbeta\n")

    def test_shrink_at_end(self) -> None:
        data = b"alpha\nbeta\ngamma\n"
        base = _snapshot(data, LineWindow(0, 3))
        updated = _apply_update(base, data, LineWindow(0, 2))
        self.assertEqual(updated.data, b"alpha\nbeta\n")

    def test_shrink_at_beginning(self) -> None:
        data = b"alpha\nbeta\ngamma\n"
        base = _snapshot(data, LineWindow(0, 2))
        updated = _apply_update(base, data, LineWindow(1, 2))
        self.assertEqual(updated.data, b"beta\n")

    def test_window_move_uses_reset_by_policy(self) -> None:
        data = b"alpha\nbeta\ngamma\n"
        base = _snapshot(data, LineWindow(0, 1))
        event = make_text_window_update(
            base,
            data,
            LineWindow(2, 3),
            seq=1,
            result_file_version="fv000001",
            result_window_version="wv000002",
        )
        self.assertIsInstance(event, ResetEvent)
        self.assertEqual(event.snapshot.data, b"gamma\n")

    def test_lines_changed_inside_window(self) -> None:
        base = _snapshot(b"alpha\nbeta\ngamma\n", LineWindow(0, 3))
        updated = _apply_update(base, b"alpha\nBETA\ngamma\n", LineWindow(0, 3))
        self.assertEqual(updated.data, b"alpha\nBETA\ngamma\n")

    def test_lines_inserted_inside_window(self) -> None:
        base = _snapshot(b"alpha\ngamma\n", LineWindow(0, 2))
        updated = _apply_update(base, b"alpha\nbeta\ngamma\n", LineWindow(0, 3))
        self.assertEqual(updated.data, b"alpha\nbeta\ngamma\n")

    def test_lines_inserted_before_window_reprojects_logical_range(self) -> None:
        base = _snapshot(b"alpha\nbeta\ngamma\n", LineWindow(1, 3))
        updated = _apply_update(base, b"zero\nalpha\nbeta\ngamma\n", LineWindow(1, 3))
        self.assertEqual(updated.data, b"alpha\nbeta\n")
        self.assertEqual(updated.total_lines, 4)

    def test_lines_removed_inside_window(self) -> None:
        base = _snapshot(b"alpha\nbeta\ngamma\n", LineWindow(0, 3))
        updated = _apply_update(base, b"alpha\ngamma\n", LineWindow(0, 2))
        self.assertEqual(updated.data, b"alpha\ngamma\n")

    def test_lines_removed_before_window_reprojects_logical_range(self) -> None:
        base = _snapshot(b"zero\nalpha\nbeta\ngamma\n", LineWindow(1, 3))
        updated = _apply_update(base, b"alpha\nbeta\ngamma\n", LineWindow(1, 3))
        self.assertEqual(updated.data, b"beta\ngamma\n")
        self.assertEqual(updated.start_byte, 6)

    def test_lines_changed_after_window_can_emit_metadata_only_delta(self) -> None:
        base = _snapshot(b"alpha\nbeta\ngamma\n", LineWindow(0, 1))
        event = make_text_window_update(
            base,
            b"alpha\nbeta\nGAMMA\n",
            LineWindow(0, 1),
            seq=1,
            result_file_version="fv000002",
            result_window_version="wv000002",
        )
        self.assertIsInstance(event, TextWindowDelta)
        self.assertEqual(event.kind, "metadata-only")
        self.assertEqual(event.ops, [])
        updated = apply_text_window_delta(base, event)
        self.assertEqual(updated.data, b"alpha\n")

    def test_file_truncated_inside_window(self) -> None:
        base = _snapshot(b"alpha\nbeta\ngamma\n", LineWindow(0, 3))
        updated = _apply_update(base, b"alpha\nbe", LineWindow(0, 3))
        self.assertEqual(updated.data, b"alpha\nbe")
        self.assertTrue(updated.truncated)

    def test_file_truncated_before_requested_window(self) -> None:
        base = _snapshot(b"alpha\nbeta\ngamma\n", LineWindow(2, 3))
        updated = _apply_update(base, b"alpha\n", LineWindow(2, 3))
        self.assertEqual(updated.data, b"")
        self.assertTrue(updated.truncated)

    def test_large_change_uses_reset(self) -> None:
        base = _snapshot(b"alpha\n", LineWindow(0, 1))
        event = make_text_window_update(
            base,
            b"x" * 100 + b"\n",
            LineWindow(0, 1),
            seq=1,
            result_file_version="fv000002",
            result_window_version="wv000002",
            delta_bytes_threshold=8,
        )
        self.assertIsInstance(event, ResetEvent)

    def test_wrong_base_window_version_rejected(self) -> None:
        base = _snapshot(b"alpha\n", LineWindow(0, 1))
        event = make_text_window_update(
            base,
            b"beta\n",
            LineWindow(0, 1),
            seq=1,
            result_file_version="fv000002",
            result_window_version="wv000002",
        )
        assert isinstance(event, TextWindowDelta)
        with self.assertRaises(DeltaApplyError):
            apply_text_window_delta(base, event, base_window_version="wv000000")

    def test_wrong_result_hash_rejected(self) -> None:
        base = _snapshot(b"alpha\n", LineWindow(0, 1))
        event = make_text_window_update(
            base,
            b"beta\n",
            LineWindow(0, 1),
            seq=1,
            result_file_version="fv000002",
            result_window_version="wv000002",
        )
        assert isinstance(event, TextWindowDelta)
        corrupted = replace(event, result_hash="sha256:bad")
        with self.assertRaises(DeltaApplyError):
            apply_text_window_delta(base, corrupted)


class DeterministicWindowReassemblyTests(unittest.TestCase):
    def test_random_reassembly_matches_direct_projection(self) -> None:
        rng = random.Random(55)
        lines = [f"line-{idx}\n".encode() for idx in range(12)]
        data = b"".join(lines)
        window = LineWindow(2, 7)
        held = _snapshot(data, window)

        for step in range(1, 25):
            action = rng.choice(["replace", "insert", "delete", "append", "truncate"])
            current_lines = data.splitlines(keepends=True)
            if action == "replace" and current_lines:
                idx = rng.randrange(len(current_lines))
                current_lines[idx] = f"replaced-{step}\n".encode()
            elif action == "insert":
                idx = rng.randrange(len(current_lines) + 1)
                current_lines.insert(idx, f"inserted-{step}\n".encode())
            elif action == "delete" and current_lines:
                del current_lines[rng.randrange(len(current_lines))]
            elif action == "append":
                current_lines.append(f"appended-{step}\n".encode())
            elif action == "truncate":
                current_lines = current_lines[: rng.randrange(len(current_lines) + 1)]
            data = b"".join(current_lines)

            start = rng.randrange(0, max(len(current_lines) + 1, 1))
            end = rng.randrange(start, max(len(current_lines) + 2, start + 1))
            new_window = LineWindow(start, end)
            event = make_text_window_update(
                held,
                data,
                new_window,
                seq=step,
                result_file_version=f"fv{step + 1:06d}",
                result_window_version=f"wv{step + 1:06d}",
            )
            if isinstance(event, ResetEvent):
                held = event.snapshot
            else:
                held = apply_text_window_delta(held, event)
            direct = make_text_window_snapshot(
                "file:window",
                "win:window",
                data,
                new_window,
                file_version=f"fv{step + 1:06d}",
                window_version=f"wv{step + 1:06d}",
            )
            self.assertEqual(held.data, direct.data)
            self.assertEqual(held.line_index, direct.line_index)


if __name__ == "__main__":
    unittest.main()

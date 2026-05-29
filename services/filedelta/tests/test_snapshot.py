from __future__ import annotations

import unittest
from dataclasses import replace

from filedelta import (
    LineWindow,
    apply_full_delta,
    apply_full_snapshot,
    make_full_delta,
    make_full_snapshot,
    make_reset,
    make_text_window_snapshot,
)
from filedelta.errors import DeltaApplyError


class FullSnapshotTests(unittest.TestCase):
    def test_empty_file_snapshot(self) -> None:
        snapshot = make_full_snapshot("file:empty", b"", file_version="fv000001")
        self.assertEqual(apply_full_snapshot(snapshot), b"")
        self.assertEqual(snapshot.size, 0)

    def test_one_line_file_snapshot(self) -> None:
        snapshot = make_full_snapshot("file:one", b"alpha\n", file_version="fv000001")
        self.assertEqual(apply_full_snapshot(snapshot), b"alpha\n")

    def test_many_line_file_snapshot(self) -> None:
        data = b"alpha\nbeta\ngamma\n"
        snapshot = make_full_snapshot("file:many", data, file_version="fv000001")
        self.assertEqual(apply_full_snapshot(snapshot), data)

    def test_crlf_preserved(self) -> None:
        data = b"alpha\r\nbeta\r\n"
        snapshot = make_full_snapshot("file:crlf", data, file_version="fv000001")
        self.assertEqual(apply_full_snapshot(snapshot), data)

    def test_utf8_multibyte_preserved(self) -> None:
        data = "alpha\ncaf\u00e9\n".encode()
        snapshot = make_full_snapshot("file:utf8", data, file_version="fv000001")
        self.assertEqual(apply_full_snapshot(snapshot), data)

    def test_snapshot_hash_mismatch_rejected(self) -> None:
        snapshot = make_full_snapshot("file:bad", b"alpha", file_version="fv000001")
        corrupted = replace(snapshot, content_hash="sha256:bad")
        with self.assertRaises(DeltaApplyError):
            apply_full_snapshot(corrupted)


class FullDeltaTests(unittest.TestCase):
    def test_append_bytes(self) -> None:
        base = b"alpha\n"
        result = b"alpha\nbeta\n"
        delta = make_full_delta(
            "file:append",
            base,
            result,
            seq=1,
            base_file_version="fv000001",
            result_file_version="fv000002",
        )
        self.assertEqual(apply_full_delta(base, delta, base_file_version="fv000001"), result)

    def test_truncate_file(self) -> None:
        base = b"alpha\nbeta\n"
        result = b"alpha\n"
        delta = make_full_delta(
            "file:truncate",
            base,
            result,
            seq=1,
            base_file_version="fv000001",
            result_file_version="fv000002",
        )
        self.assertEqual(apply_full_delta(base, delta), result)

    def test_wrong_base_version_rejected(self) -> None:
        base = b"alpha\n"
        result = b"beta\n"
        delta = make_full_delta(
            "file:version",
            base,
            result,
            seq=1,
            base_file_version="fv000001",
            result_file_version="fv000002",
        )
        with self.assertRaises(DeltaApplyError):
            apply_full_delta(base, delta, base_file_version="fv000000")

    def test_wrong_base_hash_rejected(self) -> None:
        delta = make_full_delta(
            "file:hash",
            b"alpha\n",
            b"beta\n",
            seq=1,
            base_file_version="fv000001",
            result_file_version="fv000002",
        )
        with self.assertRaises(DeltaApplyError):
            apply_full_delta(b"not-alpha\n", delta)

    def test_wrong_result_hash_rejected(self) -> None:
        delta = make_full_delta(
            "file:result-hash",
            b"alpha\n",
            b"beta\n",
            seq=1,
            base_file_version="fv000001",
            result_file_version="fv000002",
        )
        corrupted = replace(delta, result_hash="sha256:bad")
        with self.assertRaises(DeltaApplyError):
            apply_full_delta(b"alpha\n", corrupted)


class ResetTests(unittest.TestCase):
    def test_reset_snapshot_validates(self) -> None:
        snapshot = make_text_window_snapshot(
            "file:reset",
            "win:reset",
            b"alpha\nbeta\n",
            LineWindow(0, 1),
            file_version="fv000001",
            window_version="wv000001",
        )
        reset = make_reset("window-move", 2, snapshot)
        reset.validate()
        self.assertEqual(reset.snapshot.data, b"alpha\n")


if __name__ == "__main__":
    unittest.main()

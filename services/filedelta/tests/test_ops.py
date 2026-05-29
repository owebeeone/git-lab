from __future__ import annotations

import unittest

from filedelta import ByteOp, apply_ops, diff_bytes
from filedelta.errors import DeltaApplyError, DeltaValidationError


class ApplyOpsTests(unittest.TestCase):
    def test_insert_into_empty_bytes(self) -> None:
        self.assertEqual(apply_ops(b"", [ByteOp.insert(0, b"abc")]), b"abc")

    def test_insert_at_beginning_middle_end(self) -> None:
        self.assertEqual(apply_ops(b"bc", [ByteOp.insert(0, b"a")]), b"abc")
        self.assertEqual(apply_ops(b"ac", [ByteOp.insert(1, b"b")]), b"abc")
        self.assertEqual(apply_ops(b"ab", [ByteOp.insert(2, b"c")]), b"abc")

    def test_delete_at_beginning_middle_end(self) -> None:
        self.assertEqual(apply_ops(b"xabc", [ByteOp.delete(0, 1)]), b"abc")
        self.assertEqual(apply_ops(b"axbc", [ByteOp.delete(1, 1)]), b"abc")
        self.assertEqual(apply_ops(b"abcx", [ByteOp.delete(3, 1)]), b"abc")

    def test_replace_shorter_same_longer(self) -> None:
        self.assertEqual(apply_ops(b"abXXef", [ByteOp.replace(2, 2, b"c")]), b"abcef")
        self.assertEqual(apply_ops(b"abXXef", [ByteOp.replace(2, 2, b"cd")]), b"abcdef")
        self.assertEqual(apply_ops(b"abXef", [ByteOp.replace(2, 1, b"cd")]), b"abcdef")

    def test_multiple_non_overlapping_ops(self) -> None:
        ops = [ByteOp.replace(1, 1, b"B"), ByteOp.replace(3, 1, b"D")]
        self.assertEqual(apply_ops(b"abcd", ops), b"aBcD")

    def test_invalid_negative_offset(self) -> None:
        with self.assertRaises(DeltaValidationError):
            apply_ops(b"abc", [ByteOp.insert(-1, b"x")])

    def test_invalid_range_past_end(self) -> None:
        with self.assertRaises(DeltaApplyError):
            apply_ops(b"abc", [ByteOp.delete(2, 2)])

    def test_overlapping_ops_rejected(self) -> None:
        ops = [ByteOp.delete(1, 2), ByteOp.replace(2, 1, b"x")]
        with self.assertRaises(DeltaValidationError):
            apply_ops(b"abcd", ops)

    def test_empty_insert_rejected(self) -> None:
        with self.assertRaises(DeltaValidationError):
            apply_ops(b"abc", [ByteOp.insert(1, b"")])


class DiffBytesTests(unittest.TestCase):
    def assertRoundTrip(self, old: bytes, new: bytes) -> None:
        self.assertEqual(apply_ops(old, diff_bytes(old, new)), new)

    def test_diff_no_change(self) -> None:
        self.assertEqual(diff_bytes(b"abc", b"abc"), [])

    def test_diff_insert(self) -> None:
        self.assertRoundTrip(b"abef", b"abcdef")

    def test_diff_delete(self) -> None:
        self.assertRoundTrip(b"abcdef", b"abef")

    def test_diff_replace(self) -> None:
        self.assertRoundTrip(b"abXXef", b"abcdef")

    def test_diff_truncate(self) -> None:
        self.assertRoundTrip(b"abcdef", b"abc")

    def test_diff_append(self) -> None:
        self.assertRoundTrip(b"abc", b"abcdef")

    def test_diff_utf8_bytes(self) -> None:
        old = "hello cafe\n".encode()
        new = "hello cafe\u0301\n".encode()
        self.assertRoundTrip(old, new)


if __name__ == "__main__":
    unittest.main()


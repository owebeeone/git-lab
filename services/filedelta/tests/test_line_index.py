from __future__ import annotations

import unittest

from filedelta import LineWindow, build_line_index, make_text_window_snapshot, project_window


class LineIndexTests(unittest.TestCase):
    def test_line_index_for_lf(self) -> None:
        index = build_line_index(b"alpha\nbeta\ngamma\n")
        self.assertEqual(index.starts, [0, 6, 11])
        self.assertEqual(index.total_lines, 3)

    def test_line_index_for_crlf(self) -> None:
        index = build_line_index(b"alpha\r\nbeta\r\ngamma\r\n")
        self.assertEqual(index.starts, [0, 7, 13])
        self.assertEqual(index.total_lines, 3)

    def test_final_unterminated_line(self) -> None:
        index = build_line_index(b"alpha\nbeta")
        self.assertEqual(index.starts, [0, 6])
        self.assertEqual(index.total_lines, 2)


class TextWindowSnapshotTests(unittest.TestCase):
    def test_initial_window_at_start(self) -> None:
        snapshot = make_text_window_snapshot(
            "file:start",
            "win:start",
            b"alpha\nbeta\ngamma\n",
            LineWindow(0, 2),
            file_version="fv000001",
            window_version="wv000001",
        )
        self.assertEqual(snapshot.data, b"alpha\nbeta\n")
        self.assertEqual(snapshot.line_index, [0, 6])
        self.assertFalse(snapshot.truncated)

    def test_initial_window_in_middle(self) -> None:
        snapshot = make_text_window_snapshot(
            "file:middle",
            "win:middle",
            b"alpha\nbeta\ngamma\n",
            LineWindow(1, 3),
            file_version="fv000001",
            window_version="wv000001",
        )
        self.assertEqual(snapshot.data, b"beta\ngamma\n")
        self.assertEqual(snapshot.start_byte, 6)
        self.assertEqual(snapshot.end_byte, 17)
        self.assertEqual(snapshot.line_index, [0, 5])

    def test_initial_window_at_eof(self) -> None:
        snapshot = make_text_window_snapshot(
            "file:eof",
            "win:eof",
            b"alpha\nbeta\n",
            LineWindow(2, 2),
            file_version="fv000001",
            window_version="wv000001",
        )
        self.assertEqual(snapshot.data, b"")
        self.assertEqual(snapshot.start_byte, len(b"alpha\nbeta\n"))
        self.assertEqual(snapshot.end_byte, len(b"alpha\nbeta\n"))
        self.assertFalse(snapshot.truncated)

    def test_window_over_file_end_clamps_with_truncated(self) -> None:
        snapshot = make_text_window_snapshot(
            "file:over",
            "win:over",
            b"alpha\nbeta\n",
            LineWindow(1, 5),
            file_version="fv000001",
            window_version="wv000001",
        )
        self.assertEqual(snapshot.line_start, 1)
        self.assertEqual(snapshot.line_end, 2)
        self.assertEqual(snapshot.data, b"beta\n")
        self.assertTrue(snapshot.truncated)

    def test_window_bytes_contain_complete_logical_lines(self) -> None:
        projection = project_window(b"alpha\nbeta\ngamma", LineWindow(1, 2))
        self.assertEqual(projection.data, b"beta\n")

    def test_line_index_is_relative_to_window_bytes(self) -> None:
        snapshot = make_text_window_snapshot(
            "file:relative",
            "win:relative",
            b"alpha\nbeta\ngamma\n",
            LineWindow(1, 3),
            file_version="fv000001",
            window_version="wv000001",
        )
        self.assertEqual(snapshot.start_byte, 6)
        self.assertEqual(snapshot.line_index, [0, 5])

    def test_window_byte_cap_clamps_on_line_boundary(self) -> None:
        snapshot = make_text_window_snapshot(
            "file:cap",
            "win:cap",
            b"alpha\nbeta\ngamma\n",
            LineWindow(0, 3),
            file_version="fv000001",
            window_version="wv000001",
            window_bytes_cap=11,
        )
        self.assertEqual(snapshot.data, b"alpha\nbeta\n")
        self.assertEqual(snapshot.line_end, 2)
        self.assertTrue(snapshot.truncated)


if __name__ == "__main__":
    unittest.main()

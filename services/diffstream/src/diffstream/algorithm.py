"""Pure text-to-structured-hunk diff conversion."""

from __future__ import annotations

import difflib
from collections.abc import Sequence

from .errors import DiffStreamValidationError
from .model import (
    DiffEndpoint,
    DiffHunk,
    DiffLine,
    DiffPayload,
    DiffSourceState,
    DiffWindow,
    format_hunk_id,
)


def validate_same_path(left: DiffEndpoint, right: DiffEndpoint) -> None:
    """Validate the v1 same-path diff constraint."""

    left.validate()
    right.validate()
    if left.path != right.path:
        raise DiffStreamValidationError("cross-path diff is not supported in v1")


def validate_window_bounds(window: DiffWindow, total_lines: int) -> None:
    window.validate()
    if total_lines < 0:
        raise DiffStreamValidationError("total_lines must be non-negative")
    if window.line_end > total_lines:
        raise DiffStreamValidationError("window line_end is beyond source line count")


def effective_window(window: DiffWindow, context_lines: int, total_lines: int | None = None) -> DiffWindow:
    """Return the source read window expanded by context lines."""

    window.validate()
    if context_lines < 0:
        raise DiffStreamValidationError("context_lines must be non-negative")
    line_start = max(0, window.line_start - context_lines)
    line_end = window.line_end + context_lines
    if total_lines is not None:
        if total_lines < 0:
            raise DiffStreamValidationError("total_lines must be non-negative")
        line_end = min(total_lines, line_end)
    return DiffWindow(line_start=line_start, line_end=line_end, truncated=window.truncated)


def build_diff_payload(
    *,
    diff_id: str,
    version: str,
    left: DiffSourceState,
    right: DiffSourceState,
    window: DiffWindow,
    left_lines: Sequence[str],
    right_lines: Sequence[str],
    context_lines: int = 3,
    left_line_start: int | None = None,
    right_line_start: int | None = None,
    include_unified_text: bool = False,
) -> DiffPayload:
    """Build a structured diff payload from effective-window text lines."""

    validate_same_path(left.endpoint, right.endpoint)
    effective = effective_window(window, context_lines)
    left_start = effective.line_start if left_line_start is None else left_line_start
    right_start = effective.line_start if right_line_start is None else right_line_start
    if left_start < 0 or right_start < 0:
        raise DiffStreamValidationError("line starts must be non-negative")

    payload = DiffPayload(
        diff_id=diff_id,
        version=version,
        left=left,
        right=right,
        window=window,
        hunks=build_hunks(
            left_lines,
            right_lines,
            left_line_start=left_start,
            right_line_start=right_start,
            context_lines=context_lines,
        ),
        unified_text=unified_diff_text(left_lines, right_lines) if include_unified_text else None,
        diagnostics=[],
    )
    payload.validate()
    return payload


def build_hunks(
    left_lines: Sequence[str],
    right_lines: Sequence[str],
    *,
    left_line_start: int = 0,
    right_line_start: int = 0,
    context_lines: int = 3,
) -> list[DiffHunk]:
    if left_line_start < 0 or right_line_start < 0:
        raise DiffStreamValidationError("line starts must be non-negative")
    if context_lines < 0:
        raise DiffStreamValidationError("context_lines must be non-negative")

    rows = _diff_rows(left_lines, right_lines, left_line_start, right_line_start)
    intervals = _changed_intervals(rows, context_lines)
    hunks: list[DiffHunk] = []
    for index, (start, end) in enumerate(intervals, start=1):
        hunk_rows = rows[start:end]
        left_numbers = [line.left_no for line in hunk_rows if line.left_no is not None]
        right_numbers = [line.right_no for line in hunk_rows if line.right_no is not None]
        hunk = DiffHunk(
            id=format_hunk_id(index),
            left_start=min(left_numbers) if left_numbers else max(1, left_line_start + 1),
            left_lines=len(left_numbers),
            right_start=min(right_numbers) if right_numbers else max(1, right_line_start + 1),
            right_lines=len(right_numbers),
            lines=hunk_rows,
        )
        hunk.validate()
        hunks.append(hunk)
    return hunks


def unified_diff_text(
    left_lines: Sequence[str],
    right_lines: Sequence[str],
    *,
    fromfile: str = "left",
    tofile: str = "right",
) -> str:
    return "\n".join(
        difflib.unified_diff(
            list(left_lines),
            list(right_lines),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )


def _diff_rows(
    left_lines: Sequence[str],
    right_lines: Sequence[str],
    left_line_start: int,
    right_line_start: int,
) -> list[DiffLine]:
    matcher = difflib.SequenceMatcher(a=list(left_lines), b=list(right_lines), autojunk=False)
    rows: list[DiffLine] = []
    for tag, left_from, left_to, right_from, right_to in matcher.get_opcodes():
        if tag == "equal":
            for offset, (left_text, right_text) in enumerate(
                zip(left_lines[left_from:left_to], right_lines[right_from:right_to], strict=True)
            ):
                rows.append(
                    DiffLine(
                        "same",
                        left_line_start + left_from + offset + 1,
                        right_line_start + right_from + offset + 1,
                        left_text,
                        right_text,
                    )
                )
        elif tag == "delete":
            for offset, left_text in enumerate(left_lines[left_from:left_to]):
                rows.append(
                    DiffLine("del", left_line_start + left_from + offset + 1, None, left_text, None)
                )
        elif tag == "insert":
            for offset, right_text in enumerate(right_lines[right_from:right_to]):
                rows.append(
                    DiffLine("add", None, right_line_start + right_from + offset + 1, None, right_text)
                )
        elif tag == "replace":
            rows.extend(
                _replace_rows(
                    left_lines[left_from:left_to],
                    right_lines[right_from:right_to],
                    left_line_start + left_from,
                    right_line_start + right_from,
                )
            )
    for row in rows:
        row.validate()
    return rows


def _replace_rows(
    left_lines: Sequence[str],
    right_lines: Sequence[str],
    left_line_start: int,
    right_line_start: int,
) -> list[DiffLine]:
    rows: list[DiffLine] = []
    pair_count = min(len(left_lines), len(right_lines))
    for offset in range(pair_count):
        rows.append(
            DiffLine(
                "change",
                left_line_start + offset + 1,
                right_line_start + offset + 1,
                left_lines[offset],
                right_lines[offset],
            )
        )
    for offset, left_text in enumerate(left_lines[pair_count:], start=pair_count):
        rows.append(DiffLine("del", left_line_start + offset + 1, None, left_text, None))
    for offset, right_text in enumerate(right_lines[pair_count:], start=pair_count):
        rows.append(DiffLine("add", None, right_line_start + offset + 1, None, right_text))
    return rows


def _changed_intervals(rows: Sequence[DiffLine], context_lines: int) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    for index, row in enumerate(rows):
        if row.kind == "same":
            continue
        start = max(0, index - context_lines)
        end = min(len(rows), index + context_lines + 1)
        if intervals and start <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((start, end))
    return intervals

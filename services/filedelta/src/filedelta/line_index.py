"""Line indexing and byte projection for text-window snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import DeltaValidationError
from .model import LineWindow


@dataclass(frozen=True)
class LineIndex:
    """Absolute byte starts for logical lines in a file."""

    starts: list[int]
    file_size: int

    @property
    def total_lines(self) -> int:
        return len(self.starts)

    def line_start_byte(self, line: int) -> int:
        if line < 0:
            raise DeltaValidationError("line must be non-negative")
        if line >= self.total_lines:
            return self.file_size
        return self.starts[line]

    def line_end_byte(self, line_end: int) -> int:
        if line_end < 0:
            raise DeltaValidationError("line_end must be non-negative")
        if line_end >= self.total_lines:
            return self.file_size
        return self.starts[line_end]


@dataclass(frozen=True)
class WindowProjection:
    """Projected bytes plus protocol metadata for a line window."""

    line_start: int
    line_end: int
    total_lines: int
    start_byte: int
    end_byte: int
    line_index: list[int]
    truncated: bool
    data: bytes


def build_line_index(data: bytes) -> LineIndex:
    """Build absolute starts for non-empty logical file lines."""

    if not data:
        return LineIndex([], 0)

    starts = [0]
    for offset, byte in enumerate(data):
        next_offset = offset + 1
        if byte == 0x0A and next_offset < len(data):
            starts.append(next_offset)
    return LineIndex(starts, len(data))


def project_window(
    data: bytes,
    window: LineWindow,
    *,
    window_bytes_cap: int | None = None,
) -> WindowProjection:
    """Project a zero-based half-open line window into complete line bytes."""

    window.validate()
    if window_bytes_cap is not None and window_bytes_cap < 0:
        raise DeltaValidationError("window_bytes_cap must be non-negative")

    index = build_line_index(data)
    requested_start = window.line_start
    requested_end = window.line_end
    actual_start = min(requested_start, index.total_lines)
    actual_end = min(requested_end, index.total_lines)

    start_byte = index.line_start_byte(actual_start)
    end_byte = index.line_end_byte(actual_end)
    truncated = requested_end > index.total_lines or requested_start > index.total_lines

    if window_bytes_cap is not None and end_byte - start_byte > window_bytes_cap:
        truncated = True
        actual_end = actual_start
        end_byte = start_byte
        while actual_end < index.total_lines:
            candidate_end = index.line_end_byte(actual_end + 1)
            if candidate_end - start_byte > window_bytes_cap:
                break
            actual_end += 1
            end_byte = candidate_end

    window_bytes = data[start_byte:end_byte]
    relative_index = [
        line_start - start_byte
        for line_start in index.starts[actual_start:actual_end]
    ]

    return WindowProjection(
        line_start=actual_start,
        line_end=actual_end,
        total_lines=index.total_lines,
        start_byte=start_byte,
        end_byte=end_byte,
        line_index=relative_index,
        truncated=truncated,
        data=window_bytes,
    )

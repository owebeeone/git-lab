"""Structured byte delta primitives for grip-lab file windows."""

from .errors import DeltaApplyError, DeltaValidationError, FiledeltaError
from .hash import hash_bytes
from .line_index import LineIndex, WindowProjection, build_line_index, project_window
from .model import (
    ByteOp,
    CodecDescriptor,
    FileMetadata,
    FileSource,
    FullDelta,
    FullSnapshot,
    LineWindow,
    ResetEvent,
    TextWindowDelta,
    TextWindowSnapshot,
)
from .ops import apply_ops, diff_bytes
from .snapshot import (
    apply_full_delta,
    apply_full_snapshot,
    make_full_delta,
    make_full_snapshot,
    make_reset,
    make_text_window_snapshot,
)
from .window import (
    DEFAULT_DELTA_BYTES_THRESHOLD,
    apply_text_window_delta,
    classify_window_change,
    diff_text_window_snapshots,
    make_text_window_update,
)

__all__ = [
    "ByteOp",
    "CodecDescriptor",
    "DeltaApplyError",
    "DeltaValidationError",
    "FileMetadata",
    "FileSource",
    "FiledeltaError",
    "FullDelta",
    "FullSnapshot",
    "LineIndex",
    "LineWindow",
    "ResetEvent",
    "TextWindowDelta",
    "TextWindowSnapshot",
    "WindowProjection",
    "DEFAULT_DELTA_BYTES_THRESHOLD",
    "apply_ops",
    "apply_full_delta",
    "apply_full_snapshot",
    "apply_text_window_delta",
    "build_line_index",
    "classify_window_change",
    "diff_bytes",
    "diff_text_window_snapshots",
    "hash_bytes",
    "make_full_delta",
    "make_full_snapshot",
    "make_reset",
    "make_text_window_snapshot",
    "make_text_window_update",
    "project_window",
]

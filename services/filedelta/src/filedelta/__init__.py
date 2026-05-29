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
    "TextWindowSnapshot",
    "WindowProjection",
    "apply_ops",
    "apply_full_delta",
    "apply_full_snapshot",
    "build_line_index",
    "diff_bytes",
    "hash_bytes",
    "make_full_delta",
    "make_full_snapshot",
    "make_reset",
    "make_text_window_snapshot",
    "project_window",
]

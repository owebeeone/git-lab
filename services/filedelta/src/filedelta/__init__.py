"""Structured byte delta primitives for grip-lab file windows."""

from .connection import FileConnection
from .constants import DELTA_BYTES_THRESHOLD, FULL_CONTENT_SIZE_CAP, WINDOW_BYTES_CAP
from .errors import DeltaApplyError, DeltaValidationError, FiledeltaError
from .hash import hash_bytes
from .json_codec import (
    byte_op_from_json,
    byte_op_to_json,
    decode_bytes,
    encode_bytes,
    reset_from_json,
    reset_to_json,
    text_window_delta_from_json,
    text_window_delta_to_json,
    text_window_snapshot_from_json,
    text_window_snapshot_to_json,
)
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
from .subscriber import FileSubscriber
from .window import (
    DEFAULT_DELTA_BYTES_THRESHOLD,
    FileWindowSubscription,
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
    "FileConnection",
    "FileMetadata",
    "FileSource",
    "FileSubscriber",
    "FileWindowSubscription",
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
    "DELTA_BYTES_THRESHOLD",
    "FULL_CONTENT_SIZE_CAP",
    "WINDOW_BYTES_CAP",
    "apply_ops",
    "apply_full_delta",
    "apply_full_snapshot",
    "apply_text_window_delta",
    "build_line_index",
    "byte_op_from_json",
    "byte_op_to_json",
    "classify_window_change",
    "decode_bytes",
    "diff_bytes",
    "diff_text_window_snapshots",
    "encode_bytes",
    "hash_bytes",
    "make_full_delta",
    "make_full_snapshot",
    "make_reset",
    "make_text_window_snapshot",
    "make_text_window_update",
    "project_window",
    "reset_from_json",
    "reset_to_json",
    "text_window_delta_from_json",
    "text_window_delta_to_json",
    "text_window_snapshot_from_json",
    "text_window_snapshot_to_json",
]

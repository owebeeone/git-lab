"""Structured byte delta primitives for grip-lab file windows."""

from .errors import DeltaApplyError, DeltaValidationError, FiledeltaError
from .model import ByteOp, CodecDescriptor, FileMetadata, FileSource, LineWindow
from .ops import apply_ops, diff_bytes

__all__ = [
    "ByteOp",
    "CodecDescriptor",
    "DeltaApplyError",
    "DeltaValidationError",
    "FileMetadata",
    "FileSource",
    "FiledeltaError",
    "LineWindow",
    "apply_ops",
    "diff_bytes",
]


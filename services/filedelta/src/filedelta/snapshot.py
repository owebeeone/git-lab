"""Snapshot, reset, and full-content delta helpers."""

from __future__ import annotations

from .errors import DeltaApplyError
from .hash import hash_bytes
from .line_index import project_window
from .model import (
    CodecDescriptor,
    FileMetadata,
    FullDelta,
    FullSnapshot,
    LineWindow,
    ResetEvent,
    TextWindowSnapshot,
)
from .ops import apply_ops, diff_bytes


def make_full_snapshot(
    resource_id: str,
    data: bytes,
    *,
    file_version: str,
    metadata: FileMetadata | None = None,
) -> FullSnapshot:
    """Build and validate a complete file snapshot."""

    snapshot = FullSnapshot(
        resource_id=resource_id,
        file_version=file_version,
        size=len(data),
        content_hash=hash_bytes(data),
        data=data,
        metadata=metadata or FileMetadata(),
    )
    snapshot.validate()
    return snapshot


def apply_full_snapshot(snapshot: FullSnapshot) -> bytes:
    """Validate and extract a full snapshot payload."""

    snapshot.validate()
    if hash_bytes(snapshot.data) != snapshot.content_hash:
        raise DeltaApplyError("snapshot content hash mismatch")
    return snapshot.data


def make_text_window_snapshot(
    resource_id: str,
    window_id: str,
    data: bytes,
    window: LineWindow,
    *,
    file_version: str,
    window_version: str,
    metadata: FileMetadata | None = None,
    window_bytes_cap: int | None = None,
) -> TextWindowSnapshot:
    """Build and validate a line-window snapshot from file bytes."""

    projection = project_window(data, window, window_bytes_cap=window_bytes_cap)
    snapshot = TextWindowSnapshot(
        resource_id=resource_id,
        window_id=window_id,
        file_version=file_version,
        window_version=window_version,
        line_start=projection.line_start,
        line_end=projection.line_end,
        total_lines=projection.total_lines,
        start_byte=projection.start_byte,
        end_byte=projection.end_byte,
        line_index=projection.line_index,
        truncated=projection.truncated,
        size=len(projection.data),
        content_hash=hash_bytes(projection.data),
        data=projection.data,
        metadata=metadata or FileMetadata(),
    )
    snapshot.validate()
    return snapshot


def make_full_delta(
    resource_id: str,
    base_data: bytes,
    result_data: bytes,
    *,
    seq: int,
    base_file_version: str,
    result_file_version: str,
    metadata: FileMetadata | None = None,
) -> FullDelta:
    """Build a structured byte-op delta between complete file payloads."""

    delta = FullDelta(
        resource_id=resource_id,
        seq=seq,
        base_file_version=base_file_version,
        result_file_version=result_file_version,
        base_hash=hash_bytes(base_data),
        result_hash=hash_bytes(result_data),
        result_size=len(result_data),
        codec=CodecDescriptor(),
        ops=diff_bytes(base_data, result_data),
        metadata=metadata or FileMetadata(),
    )
    delta.validate()
    return delta


def apply_full_delta(
    base_data: bytes,
    delta: FullDelta,
    *,
    base_file_version: str | None = None,
) -> bytes:
    """Validate and apply a full-content delta."""

    delta.validate()
    if base_file_version is not None and delta.base_file_version != base_file_version:
        raise DeltaApplyError("base file version mismatch")
    if hash_bytes(base_data) != delta.base_hash:
        raise DeltaApplyError("base hash mismatch")
    result = apply_ops(base_data, delta.ops)
    if len(result) != delta.result_size:
        raise DeltaApplyError("result size mismatch")
    if hash_bytes(result) != delta.result_hash:
        raise DeltaApplyError("result hash mismatch")
    return result


def make_reset(
    reason: str,
    seq: int,
    snapshot: FullSnapshot | TextWindowSnapshot,
) -> ResetEvent:
    """Build and validate a reset event."""

    reset = ResetEvent(reason=reason, seq=seq, snapshot=snapshot)
    reset.validate()
    return reset

"""Text-window delta generation and apply helpers."""

from __future__ import annotations

from .errors import DeltaApplyError
from .hash import hash_bytes
from .model import (
    CodecDescriptor,
    FileMetadata,
    LineWindow,
    ResetEvent,
    TextWindowDelta,
    TextWindowSnapshot,
)
from .ops import apply_ops, diff_bytes
from .snapshot import make_reset, make_text_window_snapshot

DEFAULT_DELTA_BYTES_THRESHOLD = 64 * 1024


def classify_window_change(old: LineWindow, new: LineWindow) -> str:
    """Classify a requested window range change for event reasons."""

    old.validate()
    new.validate()
    if old.line_start == new.line_start and old.line_end == new.line_end:
        return "file-change"
    if new.line_start <= old.line_start and new.line_end >= old.line_end:
        return "window-grow"
    if new.line_start >= old.line_start and new.line_end <= old.line_end:
        return "window-shrink"
    return "window-move"


def _changed_bytes(ops) -> int:
    return sum(op.length + len(op.data) for op in ops)


def diff_text_window_snapshots(
    old: TextWindowSnapshot,
    new: TextWindowSnapshot,
    *,
    seq: int,
    reason: str,
) -> TextWindowDelta:
    """Build a text-window delta from two window snapshots."""

    old.validate()
    new.validate()
    ops = diff_bytes(old.data, new.data)
    delta = TextWindowDelta(
        resource_id=new.resource_id,
        window_id=new.window_id,
        seq=seq,
        reason=reason,
        base_file_version=old.file_version,
        result_file_version=new.file_version,
        base_window_version=old.window_version,
        result_window_version=new.window_version,
        base_hash=old.content_hash,
        result_hash=new.content_hash,
        line_start=new.line_start,
        line_end=new.line_end,
        total_lines=new.total_lines,
        start_byte=new.start_byte,
        end_byte=new.end_byte,
        line_index=new.line_index,
        truncated=new.truncated,
        result_size=new.size,
        codec=CodecDescriptor(),
        ops=ops,
        metadata=new.metadata,
        kind="metadata-only" if not ops else "content",
    )
    delta.validate()
    return delta


def make_text_window_update(
    base_snapshot: TextWindowSnapshot,
    result_file_data: bytes,
    requested_window: LineWindow,
    *,
    seq: int,
    result_file_version: str,
    result_window_version: str,
    reason: str | None = None,
    metadata: FileMetadata | None = None,
    window_bytes_cap: int | None = None,
    delta_bytes_threshold: int = DEFAULT_DELTA_BYTES_THRESHOLD,
) -> TextWindowDelta | ResetEvent:
    """Reproject a window and return either a delta or a reset event."""

    base_snapshot.validate()
    if delta_bytes_threshold < 0:
        raise DeltaApplyError("delta_bytes_threshold must be non-negative")

    base_window = LineWindow(base_snapshot.line_start, base_snapshot.line_end)
    update_reason = reason or classify_window_change(base_window, requested_window)
    result_snapshot = make_text_window_snapshot(
        base_snapshot.resource_id,
        base_snapshot.window_id,
        result_file_data,
        requested_window,
        file_version=result_file_version,
        window_version=result_window_version,
        metadata=metadata or base_snapshot.metadata,
        window_bytes_cap=window_bytes_cap,
    )

    if update_reason == "window-move":
        return make_reset(update_reason, seq, result_snapshot)

    delta = diff_text_window_snapshots(
        base_snapshot,
        result_snapshot,
        seq=seq,
        reason=update_reason,
    )
    if _changed_bytes(delta.ops) > delta_bytes_threshold:
        return make_reset("size-cap", seq, result_snapshot)
    return delta


def apply_text_window_delta(
    base_snapshot: TextWindowSnapshot,
    delta: TextWindowDelta,
    *,
    base_window_version: str | None = None,
) -> TextWindowSnapshot:
    """Validate and apply a text-window delta to a held snapshot."""

    base_snapshot.validate()
    delta.validate()
    expected_version = base_window_version or base_snapshot.window_version
    if delta.base_window_version != expected_version:
        raise DeltaApplyError("base window version mismatch")
    if delta.base_file_version != base_snapshot.file_version:
        raise DeltaApplyError("base file version mismatch")
    if hash_bytes(base_snapshot.data) != delta.base_hash:
        raise DeltaApplyError("base window hash mismatch")

    result = apply_ops(base_snapshot.data, delta.ops)
    if len(result) != delta.result_size:
        raise DeltaApplyError("result size mismatch")
    if hash_bytes(result) != delta.result_hash:
        raise DeltaApplyError("result window hash mismatch")

    snapshot = TextWindowSnapshot(
        resource_id=delta.resource_id,
        window_id=delta.window_id,
        file_version=delta.result_file_version,
        window_version=delta.result_window_version,
        line_start=delta.line_start,
        line_end=delta.line_end,
        total_lines=delta.total_lines,
        start_byte=delta.start_byte,
        end_byte=delta.end_byte,
        line_index=delta.line_index,
        truncated=delta.truncated,
        size=delta.result_size,
        content_hash=delta.result_hash,
        data=result,
        metadata=delta.metadata,
        kind="content",
    )
    snapshot.validate()
    return snapshot

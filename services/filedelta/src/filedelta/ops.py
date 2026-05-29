"""Structured byte-op apply and generation primitives."""

from __future__ import annotations

from .errors import DeltaApplyError, DeltaValidationError
from .model import ByteOp, OperationKinds


def _validate_non_overlapping_ranges(ops: list[ByteOp]) -> None:
    ranges = [op.base_range for op in ops]
    concrete = sorted(r for r in ranges if r is not None)
    for previous, current in zip(concrete, concrete[1:]):
        if current[0] < previous[1]:
            raise DeltaValidationError("ops must not overlap")


def apply_ops(data: bytes, ops: list[ByteOp]) -> bytes:
    """Apply structured byte ops to data.

    Offsets are evaluated against the current buffer as ops are applied in array
    order. Non-insert operations must not declare overlapping base ranges.
    """

    for op in ops:
        op.validate_structure()
    _validate_non_overlapping_ranges(ops)

    buf = bytearray(data)
    for op in ops:
        if op.offset > len(buf):
            raise DeltaApplyError("offset is beyond end of buffer")
        if op.op == OperationKinds.INSERT.name:
            buf[op.offset:op.offset] = op.data
            continue
        end = op.offset + op.length
        if end > len(buf):
            raise DeltaApplyError("op range is beyond end of buffer")
        if op.op == OperationKinds.DELETE.name:
            del buf[op.offset:end]
        elif op.op == OperationKinds.REPLACE.name:
            buf[op.offset:end] = op.data
        else:
            raise DeltaValidationError(f"unknown op: {op.op}")
    return bytes(buf)


def diff_bytes(old: bytes, new: bytes) -> list[ByteOp]:
    """Generate a small structured diff using common prefix/suffix trimming."""

    if old == new:
        return []

    prefix = 0
    max_prefix = min(len(old), len(new))
    while prefix < max_prefix and old[prefix] == new[prefix]:
        prefix += 1

    old_suffix = len(old)
    new_suffix = len(new)
    while (
        old_suffix > prefix
        and new_suffix > prefix
        and old[old_suffix - 1] == new[new_suffix - 1]
    ):
        old_suffix -= 1
        new_suffix -= 1

    deleted = old_suffix - prefix
    inserted = new[prefix:new_suffix]

    if deleted == 0:
        return [ByteOp.insert(prefix, inserted)]
    if not inserted:
        return [ByteOp.delete(prefix, deleted)]
    return [ByteOp.replace(prefix, deleted, inserted)]


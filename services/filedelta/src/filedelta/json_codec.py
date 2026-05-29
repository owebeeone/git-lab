"""Canonical JSON shape for filedelta protocol payloads."""

from __future__ import annotations

import base64
from typing import Any

from .model import (
    ByteOp,
    CodecDescriptor,
    FileMetadata,
    ResetEvent,
    TextWindowDelta,
    TextWindowSnapshot,
)


def encode_bytes(data: bytes) -> str:
    return "base64:" + base64.b64encode(data).decode("ascii")


def decode_bytes(value: str) -> bytes:
    if not value.startswith("base64:"):
        raise ValueError("byte payload must start with base64:")
    return base64.b64decode(value[len("base64:") :], validate=True)


def byte_op_to_json(op: ByteOp) -> dict[str, Any]:
    op.validate_structure()
    return {
        "op": op.op,
        "offset": op.offset,
        "length": op.length,
        "data": encode_bytes(op.data),
    }


def byte_op_from_json(value: dict[str, Any]) -> ByteOp:
    op = ByteOp(
        op=str(value["op"]),
        offset=int(value["offset"]),
        length=int(value.get("length", 0)),
        data=decode_bytes(str(value.get("data", "base64:"))),
    )
    op.validate_structure()
    return op


def text_window_snapshot_to_json(snapshot: TextWindowSnapshot) -> dict[str, Any]:
    snapshot.validate()
    return {
        "scope": snapshot.scope,
        "resourceId": snapshot.resource_id,
        "windowId": snapshot.window_id,
        "fileVersion": snapshot.file_version,
        "windowVersion": snapshot.window_version,
        "contentHash": snapshot.content_hash,
        "kind": snapshot.kind,
        "lineStart": snapshot.line_start,
        "lineEnd": snapshot.line_end,
        "totalLines": snapshot.total_lines,
        "startByte": snapshot.start_byte,
        "endByte": snapshot.end_byte,
        "lineIndex": snapshot.line_index,
        "truncated": snapshot.truncated,
        "size": snapshot.size,
        "data": encode_bytes(snapshot.data),
        "metadata": snapshot.metadata.values,
    }


def text_window_snapshot_from_json(value: dict[str, Any]) -> TextWindowSnapshot:
    snapshot = TextWindowSnapshot(
        resource_id=str(value["resourceId"]),
        window_id=str(value["windowId"]),
        file_version=str(value["fileVersion"]),
        window_version=str(value["windowVersion"]),
        line_start=int(value["lineStart"]),
        line_end=int(value["lineEnd"]),
        total_lines=int(value["totalLines"]),
        start_byte=int(value["startByte"]),
        end_byte=int(value["endByte"]),
        line_index=[int(item) for item in value["lineIndex"]],
        truncated=bool(value["truncated"]),
        size=int(value["size"]),
        content_hash=str(value["contentHash"]),
        data=decode_bytes(str(value["data"])),
        metadata=FileMetadata(dict(value.get("metadata", {}))),
        scope=str(value.get("scope", "text-window")),
        kind=str(value.get("kind", "content")),
    )
    snapshot.validate()
    return snapshot


def text_window_delta_to_json(delta: TextWindowDelta) -> dict[str, Any]:
    delta.validate()
    return {
        "scope": delta.scope,
        "resourceId": delta.resource_id,
        "windowId": delta.window_id,
        "seq": delta.seq,
        "reason": delta.reason,
        "baseFileVersion": delta.base_file_version,
        "resultFileVersion": delta.result_file_version,
        "baseWindowVersion": delta.base_window_version,
        "resultWindowVersion": delta.result_window_version,
        "baseHash": delta.base_hash,
        "resultHash": delta.result_hash,
        "lineStart": delta.line_start,
        "lineEnd": delta.line_end,
        "totalLines": delta.total_lines,
        "startByte": delta.start_byte,
        "endByte": delta.end_byte,
        "lineIndex": delta.line_index,
        "truncated": delta.truncated,
        "resultSize": delta.result_size,
        "codec": {"name": delta.codec.name, "version": delta.codec.version},
        "ops": [byte_op_to_json(op) for op in delta.ops],
        "metadata": delta.metadata.values,
        "kind": delta.kind,
    }


def text_window_delta_from_json(value: dict[str, Any]) -> TextWindowDelta:
    codec = value["codec"]
    delta = TextWindowDelta(
        resource_id=str(value["resourceId"]),
        window_id=str(value["windowId"]),
        seq=int(value["seq"]),
        reason=str(value["reason"]),
        base_file_version=str(value["baseFileVersion"]),
        result_file_version=str(value["resultFileVersion"]),
        base_window_version=str(value["baseWindowVersion"]),
        result_window_version=str(value["resultWindowVersion"]),
        base_hash=str(value["baseHash"]),
        result_hash=str(value["resultHash"]),
        line_start=int(value["lineStart"]),
        line_end=int(value["lineEnd"]),
        total_lines=int(value["totalLines"]),
        start_byte=int(value["startByte"]),
        end_byte=int(value["endByte"]),
        line_index=[int(item) for item in value["lineIndex"]],
        truncated=bool(value["truncated"]),
        result_size=int(value["resultSize"]),
        codec=CodecDescriptor(name=str(codec["name"]), version=int(codec["version"])),
        ops=[byte_op_from_json(op) for op in value["ops"]],
        metadata=FileMetadata(dict(value.get("metadata", {}))),
        scope=str(value.get("scope", "text-window")),
        kind=str(value.get("kind", "content")),
    )
    delta.validate()
    return delta


def reset_to_json(reset: ResetEvent) -> dict[str, Any]:
    reset.validate()
    return {
        "type": "reset",
        "reason": reset.reason,
        "seq": reset.seq,
        "snapshot": reset.snapshot.to_json_dict(),
    }


def reset_from_json(value: dict[str, Any]) -> ResetEvent:
    reset = ResetEvent(
        reason=str(value["reason"]),
        seq=int(value["seq"]),
        snapshot=TextWindowSnapshot.from_json_dict(value["snapshot"]),
    )
    reset.validate()
    return reset

"""Canonical JSON codec for structured diff payloads."""

from __future__ import annotations

from typing import Any

from .model import (
    DIFF_CONTENT_TYPE,
    DiffDiagnostic,
    DiffEndpoint,
    DiffHunk,
    DiffLine,
    DiffPayload,
    DiffRef,
    DiffSourceState,
    DiffWindow,
)


def ref_to_json(ref: DiffRef) -> dict[str, Any]:
    ref.validate()
    return {"kind": ref.kind}


def ref_from_json(value: dict[str, Any]) -> DiffRef:
    ref = DiffRef(kind=str(value["kind"]))
    ref.validate()
    return ref


def endpoint_to_json(endpoint: DiffEndpoint) -> dict[str, Any]:
    endpoint.validate()
    return {
        "peerId": endpoint.peer_id,
        "repoPath": endpoint.repo_path,
        "path": endpoint.path,
        "ref": ref_to_json(endpoint.ref),
    }


def endpoint_from_json(value: dict[str, Any]) -> DiffEndpoint:
    endpoint = DiffEndpoint(
        peer_id=str(value["peerId"]),
        repo_path=str(value.get("repoPath", "")),
        path=str(value["path"]),
        ref=ref_from_json(value["ref"]),
    )
    endpoint.validate()
    return endpoint


def window_to_json(window: DiffWindow) -> dict[str, Any]:
    window.validate()
    return {
        "lineStart": window.line_start,
        "lineEnd": window.line_end,
        "truncated": window.truncated,
    }


def window_from_json(value: dict[str, Any]) -> DiffWindow:
    window = DiffWindow(
        line_start=int(value["lineStart"]),
        line_end=int(value["lineEnd"]),
        truncated=bool(value.get("truncated", False)),
    )
    window.validate()
    return window


def source_state_to_json(state: DiffSourceState) -> dict[str, Any]:
    state.validate()
    value = endpoint_to_json(state.endpoint)
    value["fileVersion"] = state.file_version
    value["contentHash"] = state.content_hash
    return value


def source_state_from_json(value: dict[str, Any]) -> DiffSourceState:
    state = DiffSourceState(
        endpoint=endpoint_from_json(value),
        file_version=str(value["fileVersion"]),
        content_hash=str(value["contentHash"]),
    )
    state.validate()
    return state


def line_to_json(line: DiffLine) -> dict[str, Any]:
    line.validate()
    return {
        "kind": line.kind,
        "leftNo": line.left_no,
        "rightNo": line.right_no,
        "left": line.left,
        "right": line.right,
    }


def line_from_json(value: dict[str, Any]) -> DiffLine:
    line = DiffLine(
        kind=str(value["kind"]),
        left_no=_optional_int(value.get("leftNo")),
        right_no=_optional_int(value.get("rightNo")),
        left=_optional_str(value.get("left")),
        right=_optional_str(value.get("right")),
    )
    line.validate()
    return line


def hunk_to_json(hunk: DiffHunk) -> dict[str, Any]:
    hunk.validate()
    return {
        "id": hunk.id,
        "leftStart": hunk.left_start,
        "leftLines": hunk.left_lines,
        "rightStart": hunk.right_start,
        "rightLines": hunk.right_lines,
        "lines": [line_to_json(line) for line in hunk.lines],
    }


def hunk_from_json(value: dict[str, Any]) -> DiffHunk:
    hunk = DiffHunk(
        id=str(value["id"]),
        left_start=int(value["leftStart"]),
        left_lines=int(value["leftLines"]),
        right_start=int(value["rightStart"]),
        right_lines=int(value["rightLines"]),
        lines=[line_from_json(line) for line in value["lines"]],
    )
    hunk.validate()
    return hunk


def diagnostic_to_json(diagnostic: DiffDiagnostic) -> dict[str, Any]:
    diagnostic.validate()
    return {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "endpoint": diagnostic.endpoint,
        "details": diagnostic.details,
    }


def diagnostic_from_json(value: dict[str, Any]) -> DiffDiagnostic:
    diagnostic = DiffDiagnostic(
        code=str(value["code"]),
        message=str(value["message"]),
        endpoint=_optional_str(value.get("endpoint")),
        details=dict(value.get("details", {})),
    )
    diagnostic.validate()
    return diagnostic


def payload_to_json(payload: DiffPayload) -> dict[str, Any]:
    payload.validate()
    return {
        "contentType": payload.content_type,
        "diffId": payload.diff_id,
        "version": payload.version,
        "left": source_state_to_json(payload.left),
        "right": source_state_to_json(payload.right),
        "window": window_to_json(payload.window),
        "hunks": [hunk_to_json(hunk) for hunk in payload.hunks],
        "unifiedText": payload.unified_text,
        "diagnostics": [diagnostic_to_json(diagnostic) for diagnostic in payload.diagnostics],
    }


def payload_from_json(value: dict[str, Any]) -> DiffPayload:
    payload = DiffPayload(
        content_type=str(value.get("contentType", DIFF_CONTENT_TYPE)),
        diff_id=str(value["diffId"]),
        version=str(value["version"]),
        left=source_state_from_json(value["left"]),
        right=source_state_from_json(value["right"]),
        window=window_from_json(value["window"]),
        hunks=[hunk_from_json(hunk) for hunk in value["hunks"]],
        unified_text=_optional_str(value.get("unifiedText")),
        diagnostics=[diagnostic_from_json(item) for item in value.get("diagnostics", [])],
    )
    payload.validate()
    return payload


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)

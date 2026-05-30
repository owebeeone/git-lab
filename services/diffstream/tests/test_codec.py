from __future__ import annotations

import json
from pathlib import Path

import pytest

from diffstream import (
    DIFF_CONTENT_TYPE,
    DiffDiagnostic,
    DiffEndpoint,
    DiffHunk,
    DiffLine,
    DiffPayload,
    DiffRef,
    DiffSourceState,
    DiffStreamValidationError,
    DiffWindow,
    format_diff_id,
    format_diff_version,
    format_hunk_id,
    payload_from_json,
    payload_to_json,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.mark.parametrize("fixture_name", ["empty_same.json", "diagnostics.json"])
def test_fixture_round_trip_preserves_wire_fields(fixture_name: str) -> None:
    fixture = json.loads((FIXTURES / fixture_name).read_text())

    payload = payload_from_json(fixture)

    assert payload_to_json(payload) == fixture


def test_payload_to_json_uses_camel_case_wire_fields() -> None:
    payload = DiffPayload(
        diff_id=format_diff_id(1),
        version=format_diff_version(2),
        left=DiffSourceState(
            endpoint=DiffEndpoint("me", "", "src/app.ts", DiffRef("working")),
            file_version="fv000001",
            content_hash="sha256:left",
        ),
        right=DiffSourceState(
            endpoint=DiffEndpoint("peer", "", "src/app.ts", DiffRef("head")),
            file_version="fv000002",
            content_hash="sha256:right",
        ),
        window=DiffWindow(0, 10),
        hunks=[
            DiffHunk(
                id=format_hunk_id(1),
                left_start=1,
                left_lines=1,
                right_start=1,
                right_lines=1,
                lines=[DiffLine("same", 1, 1, "x", "x")],
            )
        ],
        diagnostics=[DiffDiagnostic("peer-offline", "peer is offline", "right")],
    )

    value = payload_to_json(payload)

    assert value["contentType"] == DIFF_CONTENT_TYPE
    assert value["diffId"] == "diff-000001"
    assert value["version"] == "dv000002"
    assert value["left"]["peerId"] == "me"
    assert value["left"]["fileVersion"] == "fv000001"
    assert value["window"]["lineStart"] == 0
    assert value["hunks"][0]["leftStart"] == 1
    assert value["hunks"][0]["lines"][0]["leftNo"] == 1
    assert value["unifiedText"] is None


def test_rejects_unknown_content_type() -> None:
    fixture = json.loads((FIXTURES / "empty_same.json").read_text())
    fixture["contentType"] = "application/json"

    with pytest.raises(DiffStreamValidationError, match="unsupported content type"):
        payload_from_json(fixture)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (DiffLine("add", 1, 2, "bad", "text"), "add line must not include left content"),
        (DiffLine("del", 1, 2, "text", "bad"), "del line must not include right content"),
        (DiffLine("same", 1, None, "text", "text"), "same line requires both line numbers"),
        (DiffLine("other", 1, 1, "text", "text"), "unsupported line kind"),
    ],
)
def test_rejects_invalid_line_shapes(line: DiffLine, message: str) -> None:
    with pytest.raises(DiffStreamValidationError, match=message):
        line.validate()


def test_rejects_invalid_window_and_ref() -> None:
    with pytest.raises(DiffStreamValidationError, match="line_end must be >= line_start"):
        DiffWindow(2, 1).validate()

    with pytest.raises(DiffStreamValidationError, match="unsupported ref kind"):
        DiffRef("commit").validate()


def test_rejects_unknown_diagnostic_code() -> None:
    with pytest.raises(DiffStreamValidationError, match="unsupported diagnostic code"):
        DiffDiagnostic("bad-code", "bad").validate()

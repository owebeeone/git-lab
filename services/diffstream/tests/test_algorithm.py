from __future__ import annotations

import pytest

from diffstream import (
    DiffEndpoint,
    DiffRef,
    DiffSourceState,
    DiffStreamValidationError,
    DiffWindow,
    build_diff_payload,
    build_hunks,
    effective_window,
    unified_diff_text,
    validate_same_path,
    validate_window_bounds,
)


def source_state(peer_id: str = "me", path: str = "src/app.ts") -> DiffSourceState:
    return DiffSourceState(
        endpoint=DiffEndpoint(peer_id, "", path, DiffRef("working")),
        file_version=f"fv-{peer_id}",
        content_hash=f"sha256:{peer_id}",
    )


def kinds(hunks: list) -> list[str]:
    return [line.kind for hunk in hunks for line in hunk.lines]


def test_same_lines_produce_no_hunks() -> None:
    hunks = build_hunks(["a", "b"], ["a", "b"])

    assert hunks == []


def test_insert_hunk_uses_one_based_absolute_right_lines() -> None:
    hunks = build_hunks(["a", "c"], ["a", "b", "c"], left_line_start=10, right_line_start=10, context_lines=1)

    assert len(hunks) == 1
    hunk = hunks[0]
    assert hunk.left_start == 11
    assert hunk.right_start == 11
    assert hunk.left_lines == 2
    assert hunk.right_lines == 3
    assert [(line.kind, line.left_no, line.right_no) for line in hunk.lines] == [
        ("same", 11, 11),
        ("add", None, 12),
        ("same", 12, 13),
    ]


def test_delete_hunk_uses_one_based_absolute_left_lines() -> None:
    hunks = build_hunks(["a", "b", "c"], ["a", "c"], left_line_start=4, right_line_start=4, context_lines=0)

    assert len(hunks) == 1
    assert hunks[0].left_start == 6
    assert hunks[0].right_start == 5
    assert hunks[0].left_lines == 1
    assert hunks[0].right_lines == 0
    assert kinds(hunks) == ["del"]
    assert hunks[0].lines[0].left_no == 6


def test_replace_hunk_pairs_replacement_rows() -> None:
    hunks = build_hunks(["a", "old", "c"], ["a", "new", "c"], context_lines=1)

    assert len(hunks) == 1
    assert kinds(hunks) == ["same", "change", "same"]
    assert hunks[0].lines[1].left_no == 2
    assert hunks[0].lines[1].right_no == 2
    assert hunks[0].lines[1].left == "old"
    assert hunks[0].lines[1].right == "new"


def test_separate_changes_are_split_when_context_does_not_overlap() -> None:
    hunks = build_hunks(["a", "b", "c", "d", "e"], ["A", "b", "c", "d", "E"], context_lines=0)

    assert len(hunks) == 2
    assert [hunk.id for hunk in hunks] == ["h000001", "h000002"]


def test_context_lines_merge_nearby_changes() -> None:
    hunks = build_hunks(["a", "b", "c"], ["A", "b", "C"], context_lines=1)

    assert len(hunks) == 1
    assert kinds(hunks) == ["change", "same", "change"]


def test_effective_window_expands_and_clamps_to_total() -> None:
    window = effective_window(DiffWindow(5, 10), context_lines=3, total_lines=11)

    assert window == DiffWindow(2, 11)


def test_validates_window_bounds() -> None:
    validate_window_bounds(DiffWindow(0, 3), total_lines=3)

    with pytest.raises(DiffStreamValidationError, match="beyond source line count"):
        validate_window_bounds(DiffWindow(0, 4), total_lines=3)


def test_rejects_cross_path_diff() -> None:
    with pytest.raises(DiffStreamValidationError, match="cross-path diff"):
        validate_same_path(source_state(path="a.ts").endpoint, source_state(path="b.ts").endpoint)


def test_build_diff_payload_validates_and_can_include_unified_text() -> None:
    payload = build_diff_payload(
        diff_id="diff-000001",
        version="dv000001",
        left=source_state("left"),
        right=source_state("right"),
        window=DiffWindow(0, 3),
        left_lines=["a", "old", "c"],
        right_lines=["a", "new", "c"],
        context_lines=1,
        include_unified_text=True,
    )

    assert payload.hunks[0].lines[1].kind == "change"
    assert payload.unified_text is not None
    assert "-old" in payload.unified_text
    assert "+new" in payload.unified_text


def test_unified_diff_text_uses_expected_headers() -> None:
    text = unified_diff_text(["old"], ["new"], fromfile="left.py", tofile="right.py")

    assert text.splitlines()[:2] == ["--- left.py", "+++ right.py"]

"""Protocol data structures for structured diff streams."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from .errors import DiffStreamValidationError

DIFF_CONTENT_TYPE = "application/vnd.griplab.diff+json;version=1"
SUPPORTED_REF_KINDS = frozenset({"working", "head"})
DIAGNOSTIC_CODES = frozenset(
    {
        "missing-file",
        "binary-file",
        "decode-failed",
        "window-truncated",
        "peer-offline",
        "unsupported-ref",
    }
)

DiffLineKind = Literal["same", "add", "del", "change"]
EndpointSide = Literal["left", "right"]


def format_diff_id(value: int) -> str:
    if value < 1:
        raise DiffStreamValidationError("diff id counter must be positive")
    return f"diff-{value:06d}"


def format_diff_version(value: int) -> str:
    if value < 1:
        raise DiffStreamValidationError("diff version counter must be positive")
    return f"dv{value:06d}"


def format_hunk_id(value: int) -> str:
    if value < 1:
        raise DiffStreamValidationError("hunk id counter must be positive")
    return f"h{value:06d}"


@dataclass(frozen=True)
class DiffRef:
    """Structured source ref for one diff endpoint."""

    kind: str

    def validate(self) -> None:
        if self.kind not in SUPPORTED_REF_KINDS:
            raise DiffStreamValidationError(f"unsupported ref kind: {self.kind}")


@dataclass(frozen=True)
class DiffEndpoint:
    """Stable identity for a source side of a diff."""

    peer_id: str
    repo_path: str
    path: str
    ref: DiffRef

    def validate(self) -> None:
        if not self.peer_id:
            raise DiffStreamValidationError("peer_id must not be empty")
        if not self.path:
            raise DiffStreamValidationError("path must not be empty")
        self.ref.validate()


@dataclass(frozen=True)
class DiffWindow:
    """Zero-based half-open requested source line range."""

    line_start: int
    line_end: int
    truncated: bool = False

    def validate(self) -> None:
        if self.line_start < 0:
            raise DiffStreamValidationError("line_start must be non-negative")
        if self.line_end < self.line_start:
            raise DiffStreamValidationError("line_end must be >= line_start")


@dataclass(frozen=True)
class DiffSourceState:
    """Endpoint plus source file state attached to a diff payload."""

    endpoint: DiffEndpoint
    file_version: str
    content_hash: str

    def validate(self) -> None:
        self.endpoint.validate()
        if not self.file_version:
            raise DiffStreamValidationError("file_version must not be empty")
        if not self.content_hash:
            raise DiffStreamValidationError("content_hash must not be empty")


@dataclass(frozen=True)
class DiffLine:
    """One rendered row inside a structured diff hunk."""

    kind: str
    left_no: int | None
    right_no: int | None
    left: str | None
    right: str | None

    def validate(self) -> None:
        if self.kind not in {"same", "add", "del", "change"}:
            raise DiffStreamValidationError(f"unsupported line kind: {self.kind}")
        if self.left_no is not None and self.left_no < 1:
            raise DiffStreamValidationError("left_no must be one-based when present")
        if self.right_no is not None and self.right_no < 1:
            raise DiffStreamValidationError("right_no must be one-based when present")
        if self.kind == "same":
            self._require_left_and_right("same")
        elif self.kind == "change":
            self._require_left_and_right("change")
        elif self.kind == "del":
            if self.left_no is None or self.left is None:
                raise DiffStreamValidationError("del line requires left_no and left")
            if self.right_no is not None or self.right is not None:
                raise DiffStreamValidationError("del line must not include right content")
        elif self.kind == "add":
            if self.right_no is None or self.right is None:
                raise DiffStreamValidationError("add line requires right_no and right")
            if self.left_no is not None or self.left is not None:
                raise DiffStreamValidationError("add line must not include left content")

    def _require_left_and_right(self, kind: str) -> None:
        if self.left_no is None or self.right_no is None:
            raise DiffStreamValidationError(f"{kind} line requires both line numbers")
        if self.left is None or self.right is None:
            raise DiffStreamValidationError(f"{kind} line requires both text values")


@dataclass(frozen=True)
class DiffHunk:
    """A contiguous structured diff hunk."""

    id: str
    left_start: int
    left_lines: int
    right_start: int
    right_lines: int
    lines: list[DiffLine]

    def validate(self) -> None:
        if not self.id:
            raise DiffStreamValidationError("hunk id must not be empty")
        if self.left_start < 1:
            raise DiffStreamValidationError("left_start must be one-based")
        if self.right_start < 1:
            raise DiffStreamValidationError("right_start must be one-based")
        if self.left_lines < 0 or self.right_lines < 0:
            raise DiffStreamValidationError("hunk line counts must be non-negative")
        for line in self.lines:
            line.validate()


@dataclass(frozen=True)
class DiffDiagnostic:
    """Non-fatal problem represented inside a structured diff payload."""

    code: str
    message: str
    endpoint: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.code not in DIAGNOSTIC_CODES:
            raise DiffStreamValidationError(f"unsupported diagnostic code: {self.code}")
        if not self.message:
            raise DiffStreamValidationError("diagnostic message must not be empty")
        if self.endpoint is not None and self.endpoint not in {"left", "right"}:
            raise DiffStreamValidationError("diagnostic endpoint must be left or right")


@dataclass(frozen=True)
class DiffPayload:
    """Synthetic diff payload emitted by diff.subscribe and diff.get."""

    diff_id: str
    version: str
    left: DiffSourceState
    right: DiffSourceState
    window: DiffWindow
    hunks: list[DiffHunk]
    unified_text: str | None = None
    diagnostics: list[DiffDiagnostic] = field(default_factory=list)
    content_type: str = DIFF_CONTENT_TYPE

    DEFAULT_CONTENT_TYPE: ClassVar[str] = DIFF_CONTENT_TYPE

    def validate(self) -> None:
        if self.content_type != DIFF_CONTENT_TYPE:
            raise DiffStreamValidationError(f"unsupported content type: {self.content_type}")
        if not self.diff_id.startswith("diff-"):
            raise DiffStreamValidationError("diff_id must use diff- prefix")
        if not self.version.startswith("dv"):
            raise DiffStreamValidationError("version must use dv prefix")
        self.left.validate()
        self.right.validate()
        self.window.validate()
        for hunk in self.hunks:
            hunk.validate()
        for diagnostic in self.diagnostics:
            diagnostic.validate()

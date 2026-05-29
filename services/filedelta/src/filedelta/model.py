"""Core protocol data structures for the structured byte-op codec."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from .errors import DeltaValidationError


@dataclass(frozen=True)
class CodecDescriptor:
    """Names the byte delta codec used by a payload."""

    name: str = "structured-byte-ops"
    version: int = 1

    def validate(self) -> None:
        if self.name != "structured-byte-ops":
            raise DeltaValidationError(f"unsupported codec: {self.name}")
        if self.version != 1:
            raise DeltaValidationError(f"unsupported codec version: {self.version}")


@dataclass(frozen=True)
class FileSource:
    """Stable identity for a source file/ref."""

    resource_id: str
    repo_path: str
    path: str
    ref: dict[str, Any]

    def validate(self) -> None:
        if not self.resource_id:
            raise DeltaValidationError("resource_id must not be empty")
        if not self.path:
            raise DeltaValidationError("path must not be empty")


@dataclass(frozen=True)
class LineWindow:
    """Zero-based half-open line range."""

    line_start: int
    line_end: int

    def validate(self) -> None:
        if self.line_start < 0:
            raise DeltaValidationError("line_start must be non-negative")
        if self.line_end < self.line_start:
            raise DeltaValidationError("line_end must be >= line_start")


@dataclass(frozen=True)
class FileMetadata:
    """Transport-friendly metadata attached to snapshots and deltas."""

    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FullSnapshot:
    """Complete file-content snapshot."""

    resource_id: str
    file_version: str
    size: int
    content_hash: str
    data: bytes
    metadata: FileMetadata = field(default_factory=FileMetadata)
    scope: str = "full"
    kind: str = "content"

    def validate(self) -> None:
        if self.scope != "full":
            raise DeltaValidationError("full snapshot scope must be full")
        if not self.resource_id:
            raise DeltaValidationError("resource_id must not be empty")
        if not self.file_version:
            raise DeltaValidationError("file_version must not be empty")
        if self.size != len(self.data):
            raise DeltaValidationError("snapshot size does not match data")


@dataclass(frozen=True)
class TextWindowSnapshot:
    """Snapshot for a projected line window."""

    resource_id: str
    window_id: str
    file_version: str
    window_version: str
    line_start: int
    line_end: int
    total_lines: int
    start_byte: int
    end_byte: int
    line_index: list[int]
    truncated: bool
    size: int
    content_hash: str
    data: bytes
    metadata: FileMetadata = field(default_factory=FileMetadata)
    scope: str = "text-window"
    kind: str = "content"

    def validate(self) -> None:
        if self.scope != "text-window":
            raise DeltaValidationError("text window snapshot scope must be text-window")
        if not self.resource_id:
            raise DeltaValidationError("resource_id must not be empty")
        if not self.window_id:
            raise DeltaValidationError("window_id must not be empty")
        LineWindow(self.line_start, self.line_end).validate()
        if self.total_lines < 0:
            raise DeltaValidationError("total_lines must be non-negative")
        if self.start_byte < 0 or self.end_byte < self.start_byte:
            raise DeltaValidationError("invalid byte range")
        if self.size != len(self.data):
            raise DeltaValidationError("snapshot size does not match data")
        if self.line_index and self.line_index[0] != 0:
            raise DeltaValidationError("line_index must be relative to window bytes")
        previous = -1
        for offset in self.line_index:
            if offset < 0:
                raise DeltaValidationError("line_index offsets must be non-negative")
            if offset <= previous:
                raise DeltaValidationError("line_index offsets must be increasing")
            if offset >= len(self.data) and self.data:
                raise DeltaValidationError("line_index offset is beyond window bytes")
            previous = offset


@dataclass(frozen=True)
class FullDelta:
    """Structured byte-op delta for complete file content."""

    resource_id: str
    seq: int
    base_file_version: str
    result_file_version: str
    base_hash: str
    result_hash: str
    result_size: int
    codec: CodecDescriptor
    ops: list["ByteOp"]
    metadata: FileMetadata = field(default_factory=FileMetadata)
    scope: str = "full"
    kind: str = "content"

    def validate(self) -> None:
        if self.scope != "full":
            raise DeltaValidationError("full delta scope must be full")
        if not self.resource_id:
            raise DeltaValidationError("resource_id must not be empty")
        if self.seq < 0:
            raise DeltaValidationError("seq must be non-negative")
        if not self.base_file_version or not self.result_file_version:
            raise DeltaValidationError("file versions must not be empty")
        if self.result_size < 0:
            raise DeltaValidationError("result_size must be non-negative")
        self.codec.validate()
        for op in self.ops:
            op.validate_structure()


@dataclass(frozen=True)
class ResetEvent:
    """Reset event that replaces the receiver state with a snapshot."""

    reason: str
    seq: int
    snapshot: FullSnapshot | TextWindowSnapshot

    def validate(self) -> None:
        if not self.reason:
            raise DeltaValidationError("reset reason must not be empty")
        if self.seq < 0:
            raise DeltaValidationError("seq must be non-negative")
        self.snapshot.validate()


@dataclass(frozen=True)
class OperationKind:
    """Semantic byte operation kind."""

    name: str
    requires_length: bool
    requires_data: bool


class OperationKinds:
    """Known structured byte operation kinds."""

    INSERT: ClassVar[OperationKind] = OperationKind("insert", False, True)
    DELETE: ClassVar[OperationKind] = OperationKind("delete", True, False)
    REPLACE: ClassVar[OperationKind] = OperationKind("replace", True, True)
    ALL: ClassVar[dict[str, OperationKind]] = {
        INSERT.name: INSERT,
        DELETE.name: DELETE,
        REPLACE.name: REPLACE,
    }

    @classmethod
    def by_name(cls, name: str) -> OperationKind:
        try:
            return cls.ALL[name]
        except KeyError as exc:
            raise DeltaValidationError(f"unknown op: {name}") from exc


@dataclass(frozen=True)
class ByteOp:
    """One byte-buffer operation in the structured codec."""

    op: str
    offset: int
    length: int = 0
    data: bytes = b""

    @classmethod
    def insert(cls, offset: int, data: bytes) -> ByteOp:
        return cls("insert", offset, 0, data)

    @classmethod
    def delete(cls, offset: int, length: int) -> ByteOp:
        return cls("delete", offset, length, b"")

    @classmethod
    def replace(cls, offset: int, length: int, data: bytes) -> ByteOp:
        return cls("replace", offset, length, data)

    def kind(self) -> OperationKind:
        return OperationKinds.by_name(self.op)

    def validate_structure(self) -> None:
        kind = self.kind()
        if self.offset < 0:
            raise DeltaValidationError("offset must be non-negative")
        if self.length < 0:
            raise DeltaValidationError("length must be non-negative")
        if kind.requires_length and self.length <= 0:
            raise DeltaValidationError(f"{self.op} length must be positive")
        if not kind.requires_length and self.length != 0:
            raise DeltaValidationError(f"{self.op} length must be zero")
        if kind.requires_data and not self.data:
            raise DeltaValidationError(f"{self.op} data must not be empty")
        if not kind.requires_data and self.data:
            raise DeltaValidationError(f"{self.op} data must be empty")

    @property
    def base_range(self) -> tuple[int, int] | None:
        if self.op == OperationKinds.INSERT.name:
            return None
        return (self.offset, self.offset + self.length)

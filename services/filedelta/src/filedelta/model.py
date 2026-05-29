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


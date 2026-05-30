"""JSON protocol envelope for grip-lab service messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ProtocolValidationError(ValueError):
    """Raised when a service protocol payload is structurally invalid."""


class MessageKinds:
    """Protocol envelope kind names."""

    REQUEST = "request"
    RESPONSE = "response"
    STREAM_EVENT = "stream-event"
    ERROR = "error"

    _ALL = {REQUEST, RESPONSE, STREAM_EVENT, ERROR}

    @classmethod
    def validate(cls, value: str) -> None:
        if value not in cls._ALL:
            raise ProtocolValidationError(f"unsupported message kind: {value}")


@dataclass(frozen=True)
class ErrorInfo:
    """Transport-friendly protocol error."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.code:
            raise ProtocolValidationError("error code must not be empty")
        if not self.message:
            raise ProtocolValidationError("error message must not be empty")


@dataclass(frozen=True)
class StreamEvent:
    """One event emitted on an open subscription stream."""

    stream_id: str
    seq: int
    event: str
    payload: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.stream_id:
            raise ProtocolValidationError("stream_id must not be empty")
        if self.seq < 0:
            raise ProtocolValidationError("stream seq must be non-negative")
        if not self.event:
            raise ProtocolValidationError("stream event must not be empty")


@dataclass(frozen=True)
class ProtocolEnvelope:
    """Top-level service websocket message."""

    message_id: str
    kind: str
    method: str | None = None
    stream_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    error: ErrorInfo | None = None

    @classmethod
    def request(
        cls,
        *,
        message_id: str,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> "ProtocolEnvelope":
        return cls(
            message_id=message_id,
            kind=MessageKinds.REQUEST,
            method=method,
            payload=payload or {},
        )

    @classmethod
    def response(
        cls,
        *,
        message_id: str,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> "ProtocolEnvelope":
        return cls(
            message_id=message_id,
            kind=MessageKinds.RESPONSE,
            method=method,
            payload=payload or {},
        )

    @classmethod
    def stream_event(
        cls,
        *,
        message_id: str,
        method: str,
        stream_id: str,
        event: StreamEvent,
    ) -> "ProtocolEnvelope":
        event.validate()
        if event.stream_id != stream_id:
            raise ProtocolValidationError("event stream_id must match envelope stream_id")
        return cls(
            message_id=message_id,
            kind=MessageKinds.STREAM_EVENT,
            method=method,
            stream_id=stream_id,
            payload=stream_event_to_json(event),
        )

    @classmethod
    def error_response(
        cls,
        *,
        message_id: str,
        method: str | None,
        error: ErrorInfo,
    ) -> "ProtocolEnvelope":
        error.validate()
        return cls(
            message_id=message_id,
            kind=MessageKinds.ERROR,
            method=method,
            error=error,
        )

    def validate(self) -> None:
        if not self.message_id:
            raise ProtocolValidationError("message_id must not be empty")
        MessageKinds.validate(self.kind)
        if self.kind in {MessageKinds.REQUEST, MessageKinds.RESPONSE, MessageKinds.STREAM_EVENT}:
            if not self.method:
                raise ProtocolValidationError(f"{self.kind} envelope requires method")
        if self.kind == MessageKinds.STREAM_EVENT and not self.stream_id:
            raise ProtocolValidationError("stream-event envelope requires stream_id")
        if self.kind == MessageKinds.ERROR:
            if self.error is None:
                raise ProtocolValidationError("error envelope requires error")
            self.error.validate()
        elif self.error is not None:
            raise ProtocolValidationError("non-error envelope must not include error")


def error_to_json(error: ErrorInfo) -> dict[str, Any]:
    error.validate()
    return {
        "code": error.code,
        "message": error.message,
        "details": error.details,
    }


def error_from_json(value: dict[str, Any]) -> ErrorInfo:
    error = ErrorInfo(
        code=str(value["code"]),
        message=str(value["message"]),
        details=dict(value.get("details", {})),
    )
    error.validate()
    return error


def stream_event_to_json(event: StreamEvent) -> dict[str, Any]:
    event.validate()
    return {
        "streamId": event.stream_id,
        "seq": event.seq,
        "event": event.event,
        "payload": event.payload,
    }


def stream_event_from_json(value: dict[str, Any]) -> StreamEvent:
    event = StreamEvent(
        stream_id=str(value["streamId"]),
        seq=int(value["seq"]),
        event=str(value["event"]),
        payload=dict(value.get("payload", {})),
    )
    event.validate()
    return event


def envelope_to_json(envelope: ProtocolEnvelope) -> dict[str, Any]:
    envelope.validate()
    result: dict[str, Any] = {
        "messageId": envelope.message_id,
        "kind": envelope.kind,
        "payload": envelope.payload,
    }
    if envelope.method is not None:
        result["method"] = envelope.method
    if envelope.stream_id is not None:
        result["streamId"] = envelope.stream_id
    if envelope.error is not None:
        result["error"] = error_to_json(envelope.error)
    return result


def envelope_from_json(value: dict[str, Any]) -> ProtocolEnvelope:
    error_value = value.get("error")
    envelope = ProtocolEnvelope(
        message_id=str(value["messageId"]),
        kind=str(value["kind"]),
        method=str(value["method"]) if "method" in value else None,
        stream_id=str(value["streamId"]) if "streamId" in value else None,
        payload=dict(value.get("payload", {})),
        error=error_from_json(error_value) if isinstance(error_value, dict) else None,
    )
    envelope.validate()
    return envelope

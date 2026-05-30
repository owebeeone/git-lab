from griplab_service.protocol import (
    ErrorInfo,
    ProtocolEnvelope,
    ProtocolValidationError,
    StreamEvent,
    envelope_from_json,
    envelope_to_json,
    stream_event_from_json,
    stream_event_to_json,
)


def test_request_round_trip() -> None:
    envelope = ProtocolEnvelope.request(
        message_id="m000001",
        method="workspace.status.subscribe",
        payload={"root": "."},
    )

    assert envelope_from_json(envelope_to_json(envelope)) == envelope


def test_stream_event_round_trip() -> None:
    event = StreamEvent(
        stream_id="s000001",
        seq=3,
        event="snapshot",
        payload={"repos": []},
    )
    envelope = ProtocolEnvelope.stream_event(
        message_id="m000002",
        method="workspace.status.subscribe",
        stream_id="s000001",
        event=event,
    )

    decoded = envelope_from_json(envelope_to_json(envelope))
    assert decoded == envelope
    assert stream_event_from_json(decoded.payload) == event
    assert stream_event_from_json(stream_event_to_json(event)) == event


def test_error_round_trip() -> None:
    envelope = ProtocolEnvelope.error_response(
        message_id="m000003",
        method="file.subscribe",
        error=ErrorInfo("not-found", "file does not exist", {"path": "missing.py"}),
    )

    assert envelope_from_json(envelope_to_json(envelope)) == envelope


def test_rejects_invalid_envelope_kind() -> None:
    value = {
        "messageId": "m000004",
        "kind": "unknown",
        "method": "workspace.status.subscribe",
        "payload": {},
    }

    try:
        envelope_from_json(value)
    except ProtocolValidationError as exc:
        assert "unsupported message kind" in str(exc)
    else:
        raise AssertionError("expected invalid kind to fail")


def test_rejects_stream_event_without_stream_id() -> None:
    value = {
        "messageId": "m000005",
        "kind": "stream-event",
        "method": "tree.subscribe",
        "payload": {},
    }

    try:
        envelope_from_json(value)
    except ProtocolValidationError as exc:
        assert "stream_id" in str(exc)
    else:
        raise AssertionError("expected missing stream id to fail")

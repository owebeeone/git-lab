"""Generate cross-language window reassembly fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from filedelta import (
    LineWindow,
    ResetEvent,
    TextWindowSnapshot,
    make_text_window_snapshot,
    make_text_window_update,
)

RESOURCE_ID = "file:fixture"
WINDOW_ID = "win:fixture"


def _event_json(event) -> dict:
    if isinstance(event, TextWindowSnapshot):
        return {"type": "snapshot", "snapshot": event.to_json_dict()}
    if isinstance(event, ResetEvent):
        return event.to_json_dict()
    return {"type": "delta", "delta": event.to_json_dict()}


def _case(
    name: str,
    initial_data: bytes,
    initial_window: LineWindow,
    result_data: bytes | None = None,
    result_window: LineWindow | None = None,
) -> tuple[str, list[dict[str, Any]], bytes]:
    snapshot = make_text_window_snapshot(
        RESOURCE_ID,
        WINDOW_ID,
        initial_data,
        initial_window,
        file_version="fv000001",
        window_version="wv000001",
    )
    events: list[TextWindowSnapshot | TextWindowDelta | ResetEvent] = [snapshot]
    final_snapshot = snapshot
    if result_data is not None and result_window is not None:
        event = make_text_window_update(
            snapshot,
            result_data,
            result_window,
            seq=1,
            result_file_version="fv000002",
            result_window_version="wv000002",
        )
        events.append(event)
        final_snapshot = event.snapshot if isinstance(event, ResetEvent) else make_text_window_snapshot(
            RESOURCE_ID,
            WINDOW_ID,
            result_data,
            result_window,
            file_version="fv000002",
            window_version="wv000002",
        )
    return name, [_event_json(event) for event in events], final_snapshot.data


def build_cases() -> list[tuple[str, list[dict[str, Any]], bytes]]:
    return [
        _case("start", b"alpha\nbeta\ngamma\n", LineWindow(0, 2)),
        _case(
            "reset",
            b"alpha\nbeta\ngamma\n",
            LineWindow(0, 1),
            b"alpha\nbeta\ngamma\n",
            LineWindow(2, 3),
        ),
        _case(
            "grow",
            b"alpha\nbeta\ngamma\n",
            LineWindow(1, 2),
            b"alpha\nbeta\ngamma\n",
            LineWindow(0, 3),
        ),
        _case(
            "shrink",
            b"alpha\nbeta\ngamma\n",
            LineWindow(0, 3),
            b"alpha\nbeta\ngamma\n",
            LineWindow(1, 2),
        ),
        _case(
            "lines-changed",
            b"alpha\nbeta\ngamma\n",
            LineWindow(0, 3),
            b"alpha\nBETA\ngamma\n",
            LineWindow(0, 3),
        ),
        _case(
            "lines-inserted",
            b"alpha\ngamma\n",
            LineWindow(0, 2),
            b"alpha\nbeta\ngamma\n",
            LineWindow(0, 3),
        ),
        _case(
            "lines-removed",
            b"alpha\nbeta\ngamma\n",
            LineWindow(0, 3),
            b"alpha\ngamma\n",
            LineWindow(0, 2),
        ),
        _case(
            "file-truncated",
            b"alpha\nbeta\ngamma\n",
            LineWindow(0, 3),
            b"alpha\nbe",
            LineWindow(0, 3),
        ),
        _case(
            "crlf",
            b"alpha\r\nbeta\r\n",
            LineWindow(0, 2),
            b"alpha\r\nBETA\r\n",
            LineWindow(0, 2),
        ),
        _case(
            "utf8-multibyte",
            "cafe\nbeta\n".encode(),
            LineWindow(0, 2),
            "caf\u00e9\nbeta\n".encode(),
            LineWindow(0, 2),
        ),
        _case(
            "metadata-only",
            b"alpha\nbeta\ngamma\n",
            LineWindow(0, 1),
            b"alpha\nbeta\nGAMMA\n",
            LineWindow(0, 1),
        ),
    ]


def write_fixtures(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, events, expected in build_cases():
        case_dir = output_dir / name
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "events.jsonl").write_text(
            "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
            encoding="utf-8",
        )
        (case_dir / "expected-window.bin").write_bytes(expected)
        (case_dir / "expected-window.txt").write_text(
            expected.decode("utf-8", errors="replace"),
            encoding="utf-8",
            newline="",
        )


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    write_fixtures(root / "fixtures" / "window_cases")


if __name__ == "__main__":
    main()

"""Lightweight runtime timing diagnostics for grip-lab services."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEFAULT_TRACE_FILE = "scratch/griplab-perf.jsonl"
_MAX_EVENTS = int(os.environ.get("GRIPLAB_PERF_EVENTS", "500"))
_EVENTS: deque[dict[str, Any]] = deque(maxlen=max(1, _MAX_EVENTS))
_LOCK = threading.Lock()


def enabled_for_stderr() -> bool:
    return os.environ.get("GRIPLAB_TRACE", "").lower() in {"1", "true", "yes", "on"}


def trace_file_path() -> Path | None:
    value = os.environ.get("GRIPLAB_TRACE_FILE", "")
    if value:
        return Path(value).expanduser()
    if enabled_for_stderr():
        return Path(DEFAULT_TRACE_FILE)
    return None


def now_ms() -> int:
    return int(time.time() * 1000)


def perf_counter_ms() -> float:
    return time.perf_counter() * 1000


def record(name: str, duration_ms: float, **fields: Any) -> dict[str, Any]:
    event = {
        "ts": now_ms(),
        "pid": os.getpid(),
        "name": name,
        "durationMs": round(duration_ms, 3),
        **{key: _json_safe(value) for key, value in fields.items()},
    }
    line = json.dumps({**event, "event": "perf"}, sort_keys=True)
    with _LOCK:
        _EVENTS.append(event)
        trace_file = trace_file_path()
        if trace_file is not None:
            _append_trace_file(trace_file, line)
    if enabled_for_stderr():
        print(line, file=sys.stderr, flush=True)
    return event


@contextmanager
def span(name: str, **fields: Any) -> Iterator[None]:
    started = perf_counter_ms()
    try:
        yield
    except Exception as exc:
        record(name, perf_counter_ms() - started, ok=False, error=str(exc), **fields)
        raise
    else:
        record(name, perf_counter_ms() - started, ok=True, **fields)


def recent(limit: int = 100) -> list[dict[str, Any]]:
    with _LOCK:
        events = list(_EVENTS)
    if limit <= 0:
        return []
    return events[-limit:]


def clear() -> None:
    with _LOCK:
        _EVENTS.clear()


def payload(limit: int = 100) -> dict[str, Any]:
    trace_file = trace_file_path()
    return {
        "enabled": True,
        "stderr": enabled_for_stderr(),
        "traceFile": str(trace_file) if trace_file is not None else None,
        "maxEvents": _EVENTS.maxlen,
        "events": recent(limit),
    }


def _append_trace_file(path: Path, line: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")
    except OSError as exc:
        if enabled_for_stderr():
            print(
                json.dumps({
                    "event": "perf-log-error",
                    "path": str(path),
                    "error": str(exc),
                }, sort_keys=True),
                file=sys.stderr,
                flush=True,
            )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)

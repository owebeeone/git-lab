"""Lightweight runtime timing diagnostics for grip-lab services."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Iterator

_MAX_EVENTS = int(os.environ.get("GRIPLAB_PERF_EVENTS", "500"))
_EVENTS: deque[dict[str, Any]] = deque(maxlen=max(1, _MAX_EVENTS))
_LOCK = threading.Lock()


def enabled_for_stderr() -> bool:
    return os.environ.get("GRIPLAB_TRACE", "").lower() in {"1", "true", "yes", "on"}


def now_ms() -> int:
    return int(time.time() * 1000)


def perf_counter_ms() -> float:
    return time.perf_counter() * 1000


def record(name: str, duration_ms: float, **fields: Any) -> dict[str, Any]:
    event = {
        "ts": now_ms(),
        "name": name,
        "durationMs": round(duration_ms, 3),
        **{key: _json_safe(value) for key, value in fields.items()},
    }
    with _LOCK:
        _EVENTS.append(event)
    if enabled_for_stderr():
        print(json.dumps({**event, "event": "perf"}, sort_keys=True), file=sys.stderr, flush=True)
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
    return {
        "enabled": True,
        "stderr": enabled_for_stderr(),
        "maxEvents": _EVENTS.maxlen,
        "events": recent(limit),
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)

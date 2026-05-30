"""Process restart helper for development service controls."""

from __future__ import annotations

import os
import sys
import threading


def schedule_process_restart(delay_seconds: float = 0.2) -> None:
    threading.Timer(delay_seconds, restart_process).start()


def restart_process() -> None:
    os.execv(sys.executable, [sys.executable, *sys.argv])

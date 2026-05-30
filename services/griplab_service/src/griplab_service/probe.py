"""Local service health and capability probe."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
from typing import Any

from .config import ServiceConfig


def build_probe(config: ServiceConfig) -> dict[str, Any]:
    """Return the local capability payload used by health/probe endpoints."""

    shells = []
    shell = os.environ.get("SHELL")
    if shell:
        shells.append(shell)
    return {
        "ok": True,
        "mode": config.mode,
        "selfPeerId": config.self_peer_id,
        "workspace": {
            "workspaceId": config.workspace.workspace_id,
            "root": str(config.workspace.root),
            "exists": config.workspace.root.exists(),
        },
        "capabilities": {
            "os": platform.system().lower() or "unknown",
            "platform": platform.platform(),
            "shells": shells,
            "git": shutil.which("git") is not None,
            "watchdog": importlib.util.find_spec("watchdog") is not None,
            "pty": hasattr(os, "forkpty"),
        },
    }

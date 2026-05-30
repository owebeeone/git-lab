"""Local service configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ListenConfig:
    host: str = "127.0.0.1"
    port: int = 3141

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "ListenConfig":
        host = str(value.get("host", "127.0.0.1"))
        port = int(value.get("port", 3141))
        if not host:
            raise ValueError("listen.host must not be empty")
        if port < 0 or port > 65535:
            raise ValueError("listen.port must be between 0 and 65535")
        return cls(host=host, port=port)


@dataclass(frozen=True)
class WorkspaceConfig:
    workspace_id: str
    root: Path

    @classmethod
    def from_json(cls, value: dict[str, Any], *, base_dir: Path) -> "WorkspaceConfig":
        workspace_id = str(value.get("workspaceId", "local-main"))
        root_value = str(value.get("root", "."))
        root = Path(root_value)
        if not root.is_absolute():
            root = (base_dir / root).resolve()
        if not workspace_id:
            raise ValueError("workspace.workspaceId must not be empty")
        return cls(workspace_id=workspace_id, root=root)


@dataclass(frozen=True)
class ServiceConfig:
    self_peer_id: str = "me"
    mode: str = "client"
    listen: ListenConfig = field(default_factory=ListenConfig)
    workspace: WorkspaceConfig = field(
        default_factory=lambda: WorkspaceConfig("local-main", Path(".").resolve()),
    )
    peers: list[dict[str, Any]] = field(default_factory=list)
    path: Path | None = None

    @classmethod
    def from_json(cls, value: dict[str, Any], *, path: Path | None = None) -> "ServiceConfig":
        base_dir = path.parent if path is not None else Path.cwd()
        mode = str(value.get("mode", "client"))
        if mode not in {"client", "hub"}:
            raise ValueError("mode must be client or hub")
        self_peer_id = str(value.get("selfPeerId", "me"))
        if not self_peer_id:
            raise ValueError("selfPeerId must not be empty")
        return cls(
            self_peer_id=self_peer_id,
            mode=mode,
            listen=ListenConfig.from_json(dict(value.get("listen", {}))),
            workspace=WorkspaceConfig.from_json(dict(value.get("workspace", {})), base_dir=base_dir),
            peers=list(value.get("peers", [])),
            path=path,
        )


def load_config(path: Path | str) -> ServiceConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError("config root must be an object")
    return ServiceConfig.from_json(value, path=config_path)

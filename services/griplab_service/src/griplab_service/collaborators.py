"""Collaborator records, presence payloads, and health stubs."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from griplab_service.config import ServiceConfig

PeerPresenceStatus = Literal["configured", "offline", "bootstrapping", "starting", "online", "error"]


@dataclass(frozen=True)
class CollaboratorRecord:
    peer_id: str
    name: str
    ssh_address: str
    location: str
    identity_file: str | None = None
    known_hosts_file: str | None = None
    added_at: int = field(default_factory=lambda: int(time.time() * 1000))
    probe: dict[str, Any] | None = None

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "CollaboratorRecord":
        peer_id = str(value.get("peerId", value.get("id", ""))).strip()
        if not peer_id:
            raise ValueError("collaborator peerId must not be empty")
        name = str(value.get("name", peer_id)).strip() or peer_id
        ssh_address = str(value.get("sshAddress", "")).strip()
        location = str(value.get("location", "")).strip()
        probe = value.get("probe")
        return cls(
            peer_id=peer_id,
            name=name,
            ssh_address=ssh_address,
            location=location,
            identity_file=_optional_string(value.get("identityFile")),
            known_hosts_file=_optional_string(value.get("knownHostsFile")),
            added_at=int(value.get("addedAt", int(time.time() * 1000))),
            probe=dict(probe) if isinstance(probe, dict) else None,
        )

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "peerId": self.peer_id,
            "name": self.name,
            "sshAddress": self.ssh_address,
            "location": self.location,
            "addedAt": self.added_at,
        }
        if self.identity_file:
            result["identityFile"] = self.identity_file
        if self.known_hosts_file:
            result["knownHostsFile"] = self.known_hosts_file
        if self.probe is not None:
            result["probe"] = self.probe
        return result


def resolve_config_root(config: ServiceConfig | None = None, value: str | Path | None = None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    env_value = os.environ.get("GRIPLAB_HOME")
    if env_value:
        return Path(env_value).expanduser().resolve()
    if config is not None and config.path is not None:
        return config.path.parent.resolve()
    return (Path.home() / ".griplab").resolve()


def collaborators_path(config: ServiceConfig | None = None, root: Path | None = None) -> Path:
    return (root or resolve_config_root(config)) / "collaborators.json"


def load_collaborators(path: Path) -> list[CollaboratorRecord]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, list):
        raise ValueError(f"{path.name} must contain a JSON list")
    return sorted((CollaboratorRecord.from_json(dict(item)) for item in value), key=lambda item: item.peer_id)


def write_collaborators(path: Path, collaborators: list[CollaboratorRecord]) -> None:
    write_json_private(path, [item.to_json() for item in sorted(collaborators, key=lambda value: value.peer_id)])


def upsert_collaborator(path: Path, collaborator: CollaboratorRecord) -> list[CollaboratorRecord]:
    current = [item for item in load_collaborators(path) if item.peer_id != collaborator.peer_id]
    current.append(collaborator)
    write_collaborators(path, current)
    return sorted(current, key=lambda item: item.peer_id)


def remove_collaborator(path: Path, peer_id: str) -> list[CollaboratorRecord]:
    current = [item for item in load_collaborators(path) if item.peer_id != peer_id]
    write_collaborators(path, current)
    return current


def configured_presence(record: CollaboratorRecord) -> dict[str, object]:
    return {
        "id": record.peer_id,
        "name": record.name,
        "sshAddress": record.ssh_address,
        "location": record.location,
        "os": _probe_os(record.probe),
        "shells": _probe_shells(record.probe),
        "online": False,
        "isSelf": False,
        "status": "configured",
        "summary": "Configured; not connected",
        "lastSeenAt": None,
    }


def self_presence(config: ServiceConfig) -> dict[str, object]:
    return {
        "id": config.self_peer_id,
        "name": config.self_peer_id,
        "sshAddress": "",
        "location": str(config.workspace.root),
        "os": None,
        "shells": [],
        "online": True,
        "isSelf": True,
        "status": "online",
        "summary": "Local service is running",
        "lastSeenAt": int(time.time() * 1000),
    }


def connected_presence(payload: dict[str, Any]) -> dict[str, object]:
    peer_id = str(payload.get("peerId", "")).strip()
    if not peer_id:
        raise ValueError("peer.hello requires peerId")
    return {
        "id": peer_id,
        "name": str(payload.get("name", peer_id)),
        "sshAddress": str(payload.get("sshAddress", "")),
        "location": str(payload.get("location", "")),
        "os": _normalize_os(payload.get("os")),
        "shells": [str(shell) for shell in payload.get("shells", [])] if isinstance(payload.get("shells"), list) else [],
        "online": True,
        "isSelf": bool(payload.get("isSelf", False)),
        "status": "online",
        "summary": "Connected",
        "lastSeenAt": int(time.time() * 1000),
        "clientPayload": dict(payload.get("clientPayload", {})) if isinstance(payload.get("clientPayload"), dict) else {},
    }


def mark_presence_offline(peer: dict[str, object]) -> None:
    peer["online"] = False
    peer["status"] = "offline"
    peer["summary"] = "Disconnected"
    peer["lastSeenAt"] = int(time.time() * 1000)


def health_for_presence(peer: dict[str, object]) -> dict[str, object]:
    status = str(peer.get("status", "configured"))
    peer_id = str(peer.get("id", ""))
    checks = [
        {
            "id": "config",
            "status": "ok" if peer_id else "error",
            "summary": "Peer record is present" if peer_id else "Peer id is missing",
        }
    ]
    if status == "online":
        checks.append({"id": "connection", "status": "ok", "summary": "Service websocket is connected"})
    elif status == "configured":
        checks.append({"id": "bootstrap", "status": "pending", "summary": "Bootstrap has not run yet"})
    elif status == "offline":
        checks.append({"id": "connection", "status": "error", "summary": "Service websocket is not connected"})
    return {
        "peerId": peer_id,
        "status": status,
        "summary": str(peer.get("summary", "")),
        "checks": checks,
        "updatedAt": int(time.time() * 1000),
    }


def write_json_private(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, sort_keys=True)
            f.write("\n")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    finally:
        temp_path.unlink(missing_ok=True)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    result = str(value)
    return result or None


def _probe_os(probe: dict[str, Any] | None) -> str | None:
    if not probe:
        return None
    return _normalize_os(probe.get("os") or probe.get("platform"))


def _probe_shells(probe: dict[str, Any] | None) -> list[str]:
    if not probe:
        return []
    shells = probe.get("shells", [])
    return [str(shell) for shell in shells] if isinstance(shells, list) else []


def _normalize_os(value: object) -> str | None:
    text = str(value or "").lower()
    if text.startswith("darwin") or text == "macos":
        return "macos"
    if text.startswith("linux"):
        return "linux"
    if text.startswith(("win", "mingw", "msys", "cygwin")) or text == "windows":
        return "windows"
    return None

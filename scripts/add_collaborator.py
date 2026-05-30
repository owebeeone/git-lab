#!/usr/bin/env python3
"""Add or update a GripLab collaborator record."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class Collaborator:
    peer_id: str
    name: str
    ssh_address: str
    location: str
    identity_file: str | None = None
    known_hosts_file: str | None = None
    added_at: int = field(default_factory=lambda: int(time.time() * 1000))
    probe: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "peerId": self.peer_id,
            "name": self.name,
            "sshAddress": self.ssh_address,
            "location": self.location,
            "addedAt": self.added_at,
        }
        if self.identity_file:
            value["identityFile"] = self.identity_file
        if self.known_hosts_file:
            value["knownHostsFile"] = self.known_hosts_file
        if self.probe is not None:
            value["probe"] = self.probe
        return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_root = resolve_config_root(args.config_root)
    ensure_private_dir(config_root)

    probe_result: dict[str, Any] | None = None
    if args.probe:
        with secure_temp_dir() as temp_dir:
            probe_result = run_probe(args, temp_dir)

    collaborator = Collaborator(
        peer_id=args.peer_id or default_peer_id(args.name, args.ssh_address, args.location),
        name=args.name,
        ssh_address=args.ssh_address,
        location=args.location,
        identity_file=args.identity_file,
        known_hosts_file=args.known_hosts_file,
        probe=probe_result,
    )

    collaborators_path = config_root / "collaborators.json"
    collaborators = upsert_collaborator(load_json_list(collaborators_path), collaborator.to_json())
    if not args.dry_run:
        write_json_private(collaborators_path, collaborators)

    if args.service_config:
        update_service_config(Path(args.service_config), collaborator.to_json(), dry_run=args.dry_run)
    else:
        for config_name in ("client.json", "hub.json"):
            config_path = config_root / config_name
            if config_path.exists():
                update_service_config(config_path, collaborator.to_json(), dry_run=args.dry_run)

    print(json.dumps({
        "ok": True,
        "configRoot": str(config_root),
        "collaborator": collaborator.to_json(),
        "dryRun": bool(args.dry_run),
    }, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-root", help="Durable GripLab config root. Defaults to $GRIPLAB_HOME or $HOME/.griplab.")
    parser.add_argument("--service-config", help="Optional griplab client/hub config JSON whose peers list should be updated.")
    parser.add_argument("--peer-id", help="Stable peer id. Defaults to a slug derived from name/ssh/location.")
    parser.add_argument("--name", required=True, help="Collaborator display name.")
    parser.add_argument("--ssh-address", required=True, help="SSH target, e.g. user@host or user@host:22.")
    parser.add_argument("--location", required=True, help="Remote workspace path.")
    parser.add_argument("--identity-file", help="Optional SSH identity file for this collaborator.")
    parser.add_argument("--known-hosts-file", help="Optional known_hosts file for strict host checking.")
    parser.add_argument("--probe", action="store_true", help="Probe the collaborator over SSH before writing the record.")
    parser.add_argument("--dry-run", action="store_true", help="Print the resulting record without writing files.")
    return parser


def resolve_config_root(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    env_value = os.environ.get("GRIPLAB_HOME")
    if env_value:
        return Path(env_value).expanduser().resolve()
    return (Path.home() / ".griplab").resolve()


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


@contextmanager
def secure_temp_dir() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="griplab-"))
    os.chmod(path, 0o700)
    try:
        yield path
    finally:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink(missing_ok=True)
        path.rmdir()


def run_probe(args: argparse.Namespace, temp_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sshAddress": args.ssh_address,
        "location": args.location,
    }
    if args.identity_file:
        payload["identityFile"] = args.identity_file
    if args.known_hosts_file:
        payload["knownHostsFile"] = args.known_hosts_file
    write_json_private(temp_dir / "probe-payload.json", payload)
    try:
        from griplab_service.ssh_bootstrap import probe_peer
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"griplab_service is not importable: {exc}",
        }
    return dict(probe_peer(payload))


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON list")
    return [dict(item) for item in value]


def upsert_collaborator(items: list[dict[str, Any]], collaborator: dict[str, Any]) -> list[dict[str, Any]]:
    peer_id = str(collaborator["peerId"])
    result = [item for item in items if str(item.get("peerId", "")) != peer_id]
    result.append(collaborator)
    return sorted(result, key=lambda item: str(item["peerId"]))


def update_service_config(path: Path, collaborator: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run and not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    peers = value.get("peers", [])
    if not isinstance(peers, list):
        raise ValueError(f"{path} peers field must be a list")
    value["peers"] = upsert_collaborator([dict(item) for item in peers], collaborator)
    if not dry_run:
        write_json_private(path, value)


def write_json_private(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_private_dir(path.parent)
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


def default_peer_id(name: str, ssh_address: str, location: str) -> str:
    seed = name.strip() or f"{ssh_address}-{location}"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", seed.lower()).strip("-")
    return slug or "peer"


if __name__ == "__main__":
    raise SystemExit(main())

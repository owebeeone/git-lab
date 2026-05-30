#!/usr/bin/env python3
"""Standalone GLVM command.

This file intentionally keeps the v1 implementation in one place so it can be
copied to Mac, Windows/WSL, and Raspberry Pi test machines without packaging.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


PROVIDER_NAMES = (
    "orbstack",
    "lima",
    "wsl2",
    "native-host",
    "multipass",
    "qemu",
)

DEFAULT_CONFIG = {
    "default_profile": "dev",
    "default_provider": "auto",
    "os_aliases": {
        "ubuntu-lts": "ubuntu:24.04",
        "ubuntu-stable": "ubuntu:24.04",
    },
    "network_aliases": {
        "none": {"visibility": "localhost", "outbound": False, "inbound": False},
        "full": {"visibility": "provider-default", "outbound": True, "inbound": "localhost"},
    },
    "profiles": [],
}


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    available: bool
    detail: str


@dataclass(frozen=True)
class ProjectConfig:
    path: Path | None
    default_profile: str
    default_provider: str
    profiles: list[dict[str, object]]
    os_aliases: dict[str, str]
    network_aliases: dict[str, object]


class StateError(RuntimeError):
    pass


class StateStore:
    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.lock_path = state_path.with_suffix(state_path.suffix + ".lock")

    def read(self) -> dict[str, object]:
        if not self.state_path.exists():
            return {"schema_version": 1, "bases": {}, "machines": {}}
        try:
            with self.state_path.open("r", encoding="utf-8") as state_file:
                data = json.load(state_file)
        except json.JSONDecodeError as exc:
            raise StateError(f"state file is corrupt: {self.state_path}") from exc
        if not isinstance(data, dict):
            raise StateError(f"state file must contain an object: {self.state_path}")
        return data

    def write(self, data: dict[str, object]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=self.state_path.name + ".",
                suffix=".tmp",
                dir=str(self.state_path.parent),
                text=True,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                    json.dump(data, tmp_file, indent=2, sort_keys=True)
                    tmp_file.write("\n")
                os.replace(tmp_name, self.state_path)
            finally:
                tmp_path = Path(tmp_name)
                if tmp_path.exists():
                    tmp_path.unlink()
        finally:
            self._release_lock()

    def _acquire_lock(self) -> None:
        try:
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise StateError(f"state is locked: {self.lock_path}") from exc
        else:
            os.close(fd)

    def _release_lock(self) -> None:
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="griplab-vm",
        description="Manage local GLVM test machines through pluggable providers.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="griplab-vm 0.1.0",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root used to find vm_manage/glvm.toml",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("doctor", help="Check provider availability and host readiness")
    subparsers.add_parser("providers", help="List known provider adapters")
    subparsers.add_parser("profiles", help="List project VM profiles")
    subparsers.add_parser("aliases", help="List resolved OS and network aliases")

    image_parser = subparsers.add_parser("image", help="Manage reusable provider bases")
    image_subparsers = image_parser.add_subparsers(dest="image_command")
    image_subparsers.add_parser("build", help="Build or refresh a reusable base")
    image_subparsers.add_parser("list", help="List reusable bases")
    image_subparsers.add_parser("delete", help="Delete a reusable base")

    for command, help_text in (
        ("create", "Create a machine from a profile"),
        ("start", "Start a machine"),
        ("stop", "Stop a machine"),
        ("restart", "Restart a machine"),
        ("destroy", "Destroy a machine"),
        ("list", "List known machines"),
        ("info", "Show machine details"),
        ("exec", "Run a command inside a machine"),
        ("shell", "Open an interactive shell"),
        ("ssh-config", "Render optional SSH include config"),
        ("sync", "Reconcile local state with provider reality"),
        ("repair", "Repair local state or provider references"),
    ):
        subparsers.add_parser(command, help=help_text)

    agent_parser = subparsers.add_parser("agent", help="Manage agent runs")
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command")
    agent_subparsers.add_parser("launch", help="Launch an agent run")
    agent_subparsers.add_parser("list", help="List agent runs")
    agent_subparsers.add_parser("stop", help="Stop an agent run")

    return parser


def provider_statuses() -> list[ProviderStatus]:
    return [
        ProviderStatus(name=name, available=False, detail="detection not implemented")
        for name in PROVIDER_NAMES
    ]


def parse_scalar(raw_value: str) -> object:
    value = raw_value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(part.strip()) for part in inner.split(",")]
    if value.startswith("{") and value.endswith("}"):
        return parse_inline_table(value)
    try:
        return int(value)
    except ValueError:
        return value


def parse_inline_table(raw_value: str) -> dict[str, object]:
    content = raw_value.strip()[1:-1].strip()
    table: dict[str, object] = {}
    if not content:
        return table
    for item in content.split(","):
        key, value = item.split("=", 1)
        table[key.strip()] = parse_scalar(value.strip())
    return table


def read_project_config(project_root: Path) -> ProjectConfig:
    config_path = project_root / "vm_manage" / "glvm.toml"
    data = {
        "default_profile": DEFAULT_CONFIG["default_profile"],
        "default_provider": DEFAULT_CONFIG["default_provider"],
        "os_aliases": dict(DEFAULT_CONFIG["os_aliases"]),
        "network_aliases": dict(DEFAULT_CONFIG["network_aliases"]),
        "profiles": [],
    }
    if config_path.exists():
        merge_toml_subset(config_path, data)

    return ProjectConfig(
        path=config_path if config_path.exists() else None,
        default_profile=str(data["default_profile"]),
        default_provider=str(data["default_provider"]),
        profiles=list(data["profiles"]),
        os_aliases=dict(data["os_aliases"]),
        network_aliases=dict(data["network_aliases"]),
    )


def merge_toml_subset(config_path: Path, data: dict[str, object]) -> None:
    current_section: str | None = None
    current_profile: dict[str, object] | None = None

    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[[profiles]]":
            current_section = "profiles"
            current_profile = {}
            data["profiles"].append(current_profile)  # type: ignore[union-attr]
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            current_profile = None
            continue
        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = parse_scalar(raw_value)
        if current_section == "profiles" and current_profile is not None:
            current_profile[key] = value
        elif current_section == "os_aliases":
            data["os_aliases"][key] = str(value)  # type: ignore[index]
        elif current_section == "network_aliases":
            data["network_aliases"][key] = value  # type: ignore[index]
        else:
            data[key] = value


def resolve_image_alias(config: ProjectConfig, image: str) -> str:
    return config.os_aliases.get(image, image)


def resolve_network_alias(config: ProjectConfig, network: str) -> object:
    return config.network_aliases.get(network, network)


def run_providers() -> int:
    for status in provider_statuses():
        state = "available" if status.available else "unavailable"
        print(f"{status.name}: {state} ({status.detail})")
    return 0


def run_profiles(project_root: Path) -> int:
    config = read_project_config(project_root)
    for profile in config.profiles:
        print(profile.get("name", "<unnamed>"))
    return 0


def run_aliases(project_root: Path) -> int:
    config = read_project_config(project_root)
    print("os_aliases:")
    for name, value in sorted(config.os_aliases.items()):
        print(f"  {name} = {value}")
    print("network_aliases:")
    for name, value in sorted(config.network_aliases.items()):
        print(f"  {name} = {value}")
    return 0


def run_doctor() -> int:
    print("griplab-vm doctor")
    print("provider detection is not implemented in this checkpoint")
    return run_providers()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    if args.command == "doctor":
        return run_doctor()
    if args.command == "providers":
        return run_providers()
    if args.command == "profiles":
        return run_profiles(Path(args.project_root))
    if args.command == "aliases":
        return run_aliases(Path(args.project_root))
    if args.command is None:
        parser.print_help()
        return 0

    parser.error(f"command '{args.command}' is declared but not implemented yet")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Standalone GLVM command.

This file intentionally keeps the v1 implementation in one place so it can be
copied to Mac, Windows/WSL, and Raspberry Pi test machines without packaging.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
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

BASE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    available: bool
    detail: str


@dataclass(frozen=True)
class ProviderCapabilities:
    true_vm_boundary: bool
    cloud_init: bool
    host_mounts: bool
    read_only_mounts: bool
    explicit_port_forwards: bool
    provider_ssh: bool
    snapshots: bool
    clone: bool
    custom_images: bool
    cross_arch: bool
    rootless_daily_ops: bool


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    command: str | None
    host_systems: tuple[str, ...]
    capabilities: ProviderCapabilities
    detail: str

    def detect(self) -> ProviderStatus:
        system = platform.system().lower()
        if self.host_systems and system not in self.host_systems:
            return ProviderStatus(self.name, False, f"unsupported on {system or 'unknown'}")
        if self.command is None:
            return ProviderStatus(self.name, True, self.detail)
        if shutil.which(self.command) is None:
            return ProviderStatus(self.name, False, f"missing command: {self.command}")
        return ProviderStatus(self.name, True, f"{self.command} found")


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
    parser.add_argument(
        "--state-file",
        help="Local state file path; defaults to user config state",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("doctor", help="Check provider availability and host readiness")
    subparsers.add_parser("providers", help="List known provider adapters")
    subparsers.add_parser("profiles", help="List project VM profiles")
    subparsers.add_parser("aliases", help="List resolved OS and network aliases")

    image_parser = subparsers.add_parser("image", help="Manage reusable provider bases")
    image_subparsers = image_parser.add_subparsers(dest="image_command")
    image_build = image_subparsers.add_parser("build", help="Build or refresh a reusable base")
    image_build.add_argument("--profile", required=True, help="Profile name to build")
    image_build.add_argument("--name", required=True, help="Reusable base name")
    image_build.add_argument("--provider", help="Provider name override")
    image_subparsers.add_parser("list", help="List reusable bases")
    image_delete = image_subparsers.add_parser("delete", help="Delete a reusable base")
    image_delete.add_argument("name", help="Reusable base name")

    create_parser = subparsers.add_parser("create", help="Create a machine from a profile")
    create_parser.add_argument("--provider", help="Provider name override")
    create_parser.add_argument("--profile", required=True, help="Profile name")
    create_parser.add_argument("--name", required=True, help="Machine name")
    create_parser.add_argument("--distro", help="Existing WSL distro name to attach")

    destroy_parser = subparsers.add_parser("destroy", help="Destroy a machine")
    destroy_parser.add_argument("name", help="Machine name")

    info_parser = subparsers.add_parser("info", help="Show machine details")
    info_parser.add_argument("name", help="Machine name")

    exec_parser = subparsers.add_parser("exec", help="Run a command inside a machine")
    exec_parser.add_argument("name", help="Machine name")
    exec_parser.add_argument("exec_command", nargs=argparse.REMAINDER, help="Command to run")

    for command, help_text in (
        ("start", "Start a machine"),
        ("stop", "Stop a machine"),
        ("restart", "Restart a machine"),
        ("list", "List known machines"),
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
    return [definition.detect() for definition in provider_definitions()]


def provider_definitions() -> list[ProviderDefinition]:
    return [
        ProviderDefinition(
            name="orbstack",
            command="orb",
            host_systems=("darwin",),
            capabilities=ProviderCapabilities(
                true_vm_boundary=True,
                cloud_init=True,
                host_mounts=True,
                read_only_mounts=False,
                explicit_port_forwards=True,
                provider_ssh=True,
                snapshots=False,
                clone=True,
                custom_images=True,
                cross_arch=False,
                rootless_daily_ops=True,
            ),
            detail="macOS OrbStack machine provider",
        ),
        ProviderDefinition(
            name="lima",
            command="limactl",
            host_systems=("darwin", "linux"),
            capabilities=ProviderCapabilities(
                true_vm_boundary=True,
                cloud_init=True,
                host_mounts=True,
                read_only_mounts=True,
                explicit_port_forwards=True,
                provider_ssh=True,
                snapshots=False,
                clone=False,
                custom_images=True,
                cross_arch=True,
                rootless_daily_ops=True,
            ),
            detail="Lima VM provider",
        ),
        ProviderDefinition(
            name="wsl2",
            command="wsl",
            host_systems=("windows",),
            capabilities=ProviderCapabilities(
                true_vm_boundary=False,
                cloud_init=False,
                host_mounts=True,
                read_only_mounts=False,
                explicit_port_forwards=False,
                provider_ssh=False,
                snapshots=False,
                clone=False,
                custom_images=True,
                cross_arch=False,
                rootless_daily_ops=True,
            ),
            detail="Windows WSL2 machine provider",
        ),
        ProviderDefinition(
            name="native-host",
            command=None,
            host_systems=("darwin", "linux", "windows"),
            capabilities=ProviderCapabilities(
                true_vm_boundary=False,
                cloud_init=False,
                host_mounts=True,
                read_only_mounts=False,
                explicit_port_forwards=False,
                provider_ssh=False,
                snapshots=False,
                clone=False,
                custom_images=False,
                cross_arch=False,
                rootless_daily_ops=True,
            ),
            detail="current host command provider",
        ),
        ProviderDefinition(
            name="multipass",
            command="multipass",
            host_systems=("darwin", "linux", "windows"),
            capabilities=ProviderCapabilities(
                true_vm_boundary=True,
                cloud_init=True,
                host_mounts=True,
                read_only_mounts=False,
                explicit_port_forwards=True,
                provider_ssh=False,
                snapshots=True,
                clone=False,
                custom_images=True,
                cross_arch=False,
                rootless_daily_ops=True,
            ),
            detail="Canonical Multipass VM provider",
        ),
        ProviderDefinition(
            name="qemu",
            command="qemu-img",
            host_systems=("darwin", "linux"),
            capabilities=ProviderCapabilities(
                true_vm_boundary=True,
                cloud_init=True,
                host_mounts=True,
                read_only_mounts=False,
                explicit_port_forwards=True,
                provider_ssh=False,
                snapshots=True,
                clone=True,
                custom_images=True,
                cross_arch=True,
                rootless_daily_ops=True,
            ),
            detail="raw QEMU provider",
        ),
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


def default_state_path() -> Path:
    if platform.system().lower() == "windows":
        root = os.environ.get("APPDATA")
        if root:
            return Path(root) / "griplab-vm" / "state.json"
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "griplab-vm" / "state.json"
    return Path.home() / ".config" / "griplab-vm" / "state.json"


def state_store_from_args(args: argparse.Namespace) -> StateStore:
    if args.state_file:
        return StateStore(Path(args.state_file))
    return StateStore(default_state_path())


def find_profile(config: ProjectConfig, name: str) -> dict[str, object]:
    for profile in config.profiles:
        if profile.get("name") == name:
            return profile
    raise ValueError(f"profile not found: {name}")


def resolved_profile_inputs(
    config: ProjectConfig,
    profile: dict[str, object],
    provider: str,
) -> dict[str, object]:
    image_alias = str(profile.get("image", "ubuntu-lts"))
    network_alias = str(profile.get("network", "none"))
    return {
        "base_schema_version": BASE_SCHEMA_VERSION,
        "provider": provider,
        "profile": profile.get("name"),
        "image_alias": image_alias,
        "resolved_image": resolve_image_alias(config, image_alias),
        "network_alias": network_alias,
        "resolved_network": resolve_network_alias(config, network_alias),
        "cpus": profile.get("cpus"),
        "memory": profile.get("memory"),
        "disk": profile.get("disk"),
        "mounts": profile.get("mounts", []),
        "tools": profile.get("tools", []),
        "packages": profile.get("packages", []),
    }


def base_fingerprint(inputs: dict[str, object]) -> str:
    payload = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def choose_provider(config: ProjectConfig, override: str | None) -> str:
    if override:
        return override
    if config.default_provider != "auto":
        return config.default_provider
    return "orbstack"


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


def run_image(args: argparse.Namespace) -> int:
    if args.image_command == "build":
        return run_image_build(args)
    if args.image_command == "list":
        return run_image_list(args)
    if args.image_command == "delete":
        return run_image_delete(args)
    print("image command required")
    return 2


def run_image_build(args: argparse.Namespace) -> int:
    config = read_project_config(Path(args.project_root))
    profile = find_profile(config, args.profile)
    provider = choose_provider(config, args.provider)
    inputs = resolved_profile_inputs(config, profile, provider)
    fingerprint = base_fingerprint(inputs)

    store = state_store_from_args(args)
    state = store.read()
    bases = state.setdefault("bases", {})
    if not isinstance(bases, dict):
        raise StateError("state field 'bases' must be an object")

    previous = bases.get(args.name)
    stale = isinstance(previous, dict) and previous.get("fingerprint") != fingerprint
    bases[args.name] = {
        "provider": provider,
        "provider_id": f"glvm-base-{args.name}",
        "profile": args.profile,
        "image_alias": inputs["image_alias"],
        "resolved_image": inputs["resolved_image"],
        "network_alias": inputs["network_alias"],
        "resolved_network": inputs["resolved_network"],
        "tools": inputs["tools"],
        "packages": inputs["packages"],
        "fingerprint": fingerprint,
        "stale": False,
        "created_at": utc_now(),
    }
    store.write(state)

    status = "rebuilt" if stale else "built"
    print(f"{status} base {args.name} ({provider})")
    return 0


def run_image_list(args: argparse.Namespace) -> int:
    state = state_store_from_args(args).read()
    bases = state.get("bases", {})
    if not isinstance(bases, dict):
        raise StateError("state field 'bases' must be an object")
    for name, base in sorted(bases.items()):
        if isinstance(base, dict):
            provider = base.get("provider", "unknown")
            profile = base.get("profile", "unknown")
            stale = " stale" if base.get("stale") else ""
            print(f"{name}: {provider} profile={profile}{stale}")
    return 0


def run_image_delete(args: argparse.Namespace) -> int:
    store = state_store_from_args(args)
    state = store.read()
    bases = state.get("bases", {})
    if not isinstance(bases, dict):
        raise StateError("state field 'bases' must be an object")
    if args.name in bases:
        del bases[args.name]
        store.write(state)
        print(f"deleted base {args.name}")
    else:
        print(f"base not found: {args.name}")
    return 0


def state_machines(state: dict[str, object]) -> dict[str, object]:
    machines = state.setdefault("machines", {})
    if not isinstance(machines, dict):
        raise StateError("state field 'machines' must be an object")
    return machines


def run_create(args: argparse.Namespace) -> int:
    config = read_project_config(Path(args.project_root))
    profile = find_profile(config, args.profile)
    provider = choose_provider(config, args.provider)
    if provider == "wsl2":
        return run_create_wsl2(args, config, profile)
    if provider != "native-host":
        print(f"provider not implemented for create: {provider}")
        return 2

    inputs = resolved_profile_inputs(config, profile, provider)
    store = state_store_from_args(args)
    state = store.read()
    machines = state_machines(state)
    if args.name in machines:
        print(f"machine already exists: {args.name}")
        return 2

    machines[args.name] = {
        "provider": "native-host",
        "provider_id": f"native-host:{args.name}",
        "profile": args.profile,
        "image_alias": inputs["image_alias"],
        "resolved_image": inputs["resolved_image"],
        "network_alias": inputs["network_alias"],
        "resolved_network": inputs["resolved_network"],
        "state": "registered",
        "owner": getpass.getuser(),
        "host_system": platform.system().lower(),
        "host_machine": platform.machine(),
        "created_at": utc_now(),
        "last_seen_at": utc_now(),
    }
    store.write(state)
    print(f"created machine {args.name} (native-host)")
    return 0


def run_create_wsl2(
    args: argparse.Namespace,
    config: ProjectConfig,
    profile: dict[str, object],
) -> int:
    if not args.distro:
        print("wsl2 create requires --distro for v1 attach mode")
        return 2

    inputs = resolved_profile_inputs(config, profile, "wsl2")
    store = state_store_from_args(args)
    state = store.read()
    machines = state_machines(state)
    if args.name in machines:
        print(f"machine already exists: {args.name}")
        return 2

    machines[args.name] = {
        "provider": "wsl2",
        "provider_id": args.distro,
        "profile": args.profile,
        "image_alias": inputs["image_alias"],
        "resolved_image": inputs["resolved_image"],
        "network_alias": inputs["network_alias"],
        "resolved_network": inputs["resolved_network"],
        "state": "attached",
        "owner": getpass.getuser(),
        "owned": False,
        "created_at": utc_now(),
        "last_seen_at": utc_now(),
    }
    store.write(state)
    print(f"attached machine {args.name} (wsl2:{args.distro})")
    return 0


def run_list(args: argparse.Namespace) -> int:
    state = state_store_from_args(args).read()
    machines = state.get("machines", {})
    if not isinstance(machines, dict):
        raise StateError("state field 'machines' must be an object")
    for name, machine in sorted(machines.items()):
        if isinstance(machine, dict):
            provider = machine.get("provider", "unknown")
            status = machine.get("state", "unknown")
            profile = machine.get("profile", "unknown")
            print(f"{name}: {provider} profile={profile} state={status}")
    return 0


def run_info(args: argparse.Namespace) -> int:
    machine = require_machine(state_store_from_args(args).read(), args.name)
    print(json.dumps(machine, indent=2, sort_keys=True))
    return 0


def run_destroy(args: argparse.Namespace) -> int:
    store = state_store_from_args(args)
    state = store.read()
    machines = state_machines(state)
    machine = machines.get(args.name)
    if not isinstance(machine, dict):
        print(f"machine not found: {args.name}")
        return 2
    if machine.get("provider") == "wsl2" and machine.get("owned") is False:
        del machines[args.name]
        store.write(state)
        print(f"detached machine {args.name}")
        return 0
    if machine.get("provider") != "native-host":
        print(f"provider not implemented for destroy: {machine.get('provider')}")
        return 2
    del machines[args.name]
    store.write(state)
    print(f"destroyed machine {args.name}")
    return 0


def require_machine(state: dict[str, object], name: str) -> dict[str, object]:
    machines = state.get("machines", {})
    if not isinstance(machines, dict):
        raise StateError("state field 'machines' must be an object")
    machine = machines.get(name)
    if not isinstance(machine, dict):
        raise StateError(f"machine not found: {name}")
    return machine


def run_exec(args: argparse.Namespace) -> int:
    command = list(args.exec_command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("exec command required")
        return 2

    machine = require_machine(state_store_from_args(args).read(), args.name)
    provider = machine.get("provider")
    if provider == "wsl2":
        distro = str(machine.get("provider_id"))
        result = subprocess.run(
            ["wsl", "--distribution", distro, "--"] + command,
            check=False,
        )
        return int(result.returncode)
    if provider != "native-host":
        print(f"provider not implemented for exec: {machine.get('provider')}")
        return 2

    result = subprocess.run(command, check=False)
    return int(result.returncode)


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
    if args.command == "image":
        return run_image(args)
    if args.command == "create":
        return run_create(args)
    if args.command == "list":
        return run_list(args)
    if args.command == "info":
        return run_info(args)
    if args.command == "destroy":
        return run_destroy(args)
    if args.command == "exec":
        return run_exec(args)
    if args.command is None:
        parser.print_help()
        return 0

    parser.error(f"command '{args.command}' is declared but not implemented yet")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Standalone GLVM command.

This file intentionally keeps the v1 implementation in one place so it can be
copied to Mac, Windows/WSL, and Raspberry Pi test machines without packaging.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Sequence


PROVIDER_NAMES = (
    "orbstack",
    "lima",
    "wsl2",
    "native-host",
    "multipass",
    "qemu",
)


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    available: bool
    detail: str


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


def run_providers() -> int:
    for status in provider_statuses():
        state = "available" if status.available else "unavailable"
        print(f"{status.name}: {state} ({status.detail})")
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
    if args.command is None:
        parser.print_help()
        return 0

    parser.error(f"command '{args.command}' is declared but not implemented yet")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

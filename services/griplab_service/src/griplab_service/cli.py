"""CLI entrypoints for local grip-lab services."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from pathlib import Path
from urllib.request import urlopen

from .config import load_config
from .hub import HubServer
from .hub_registration import HubRegistrationClient
from .local_client import LocalClientServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="griplab")
    sub = parser.add_subparsers(dest="command", required=True)

    client = sub.add_parser("client")
    client.add_argument("--config", required=True)

    probe = sub.add_parser("probe")
    probe.add_argument("--config", required=True)

    hub = sub.add_parser("hub")
    hub.add_argument("--config", required=True)

    return parser


def run_client(config_path: Path) -> int:
    config = load_config(config_path)
    server = LocalClientServer(config)
    hub_registration = HubRegistrationClient(config)
    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    server.start()
    hub_registration.start()
    print(json.dumps({"ok": True, "url": server.url}, sort_keys=True), flush=True)
    stop_event.wait()
    hub_registration.stop()
    server.stop()
    return 0


def run_probe(config_path: Path) -> int:
    config = load_config(config_path)
    server = LocalClientServer(config)
    server.start()
    try:
        with urlopen(f"{server.url}/probe", timeout=2) as response:
            sys.stdout.write(response.read().decode("utf-8"))
            sys.stdout.write("\n")
    finally:
        server.stop()
    return 0


def run_hub(config_path: Path) -> int:
    config = load_config(config_path)
    server = HubServer(config)
    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    server.start()
    print(json.dumps({"ok": True, "url": server.url}, sort_keys=True), flush=True)
    stop_event.wait()
    server.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config)
    if args.command == "client":
        return run_client(config_path)
    if args.command == "probe":
        return run_probe(config_path)
    if args.command == "hub":
        return run_hub(config_path)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

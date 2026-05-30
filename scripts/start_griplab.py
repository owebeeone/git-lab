#!/usr/bin/env python3
"""Start GripLab from the default user config root."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CLIENT_PORT = 3141
DEFAULT_HUB_PORT = 3140


@dataclass
class StartedProcess:
    name: str
    process: subprocess.Popen[bytes]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    config_root = resolve_config_root(args.config_root)
    ensure_private_dir(config_root)
    workspace_root = Path(args.workspace).expanduser().resolve() if args.workspace else repo_root

    client_config = config_root / "client.json"
    hub_config = config_root / "hub.json"
    write_default_config(
        client_config,
        self_peer_id=args.peer_id,
        mode="client",
        port=args.client_port,
        workspace_id="local-main",
        workspace_root=workspace_root,
    )
    write_default_config(
        hub_config,
        self_peer_id="hub",
        mode="hub",
        port=args.hub_port,
        workspace_id="hub-main",
        workspace_root=workspace_root,
    )
    sync_collaborators(config_root, [client_config, hub_config])
    if args.with_hub:
        sync_local_hub_registration(client_config, hub_port=args.hub_port)

    ui_service_port = args.hub_port if args.with_hub else args.client_port
    hub_route = args.with_hub

    if args.build or args.prod:
        run_checked(["npm", "run", "build"], cwd=repo_root, env=ui_env(service=not args.mock, service_port=ui_service_port, hub_route=hub_route))

    processes: list[StartedProcess] = []
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        stop_processes(processes)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        if args.mock:
            processes.append(start_ui(repo_root, service=False, prod=args.prod, service_port=ui_service_port))
        elif args.hub_only:
            processes.append(start_service(repo_root, "hub", hub_config))
        else:
            if args.with_hub:
                processes.append(start_service(repo_root, "hub", hub_config))
            if not args.no_service:
                processes.append(start_service(repo_root, "client", client_config))
            if not args.no_ui:
                processes.append(start_ui(repo_root, service=True, prod=args.prod, service_port=ui_service_port, hub_route=hub_route))
        print_startup_summary(config_root, client_config, hub_config, processes)
        while processes and not stopping:
            for item in list(processes):
                code = item.process.poll()
                if code is not None:
                    print(f"{item.name} exited with code {code}", file=sys.stderr, flush=True)
                    stop_processes(processes)
                    return int(code)
            time.sleep(0.25)
        return 0
    finally:
        stop_processes(processes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-root", help="Config root. Defaults to $GRIPLAB_HOME or $HOME/.griplab.")
    parser.add_argument("--workspace", help="Workspace root for generated configs. Defaults to this repo root.")
    parser.add_argument("--peer-id", default="me", help="Local peer id for the generated client config.")
    parser.add_argument("--client-port", type=int, default=DEFAULT_CLIENT_PORT)
    parser.add_argument("--hub-port", type=int, default=DEFAULT_HUB_PORT)
    parser.add_argument("--build", action="store_true", help="Run npm build before starting.")
    parser.add_argument("--prod", action="store_true", help="Run npm build and serve the production build with Vite preview.")
    parser.add_argument("--mock", action="store_true", help="Run the mock UI only; do not start Python services.")
    parser.add_argument("--hub-only", action="store_true", help="Start only the hub using the default hub config.")
    parser.add_argument("--with-hub", action="store_true", help="Start the hub alongside the local client and UI.")
    parser.add_argument("--no-service", action="store_true", help="Do not start the local Python client service.")
    parser.add_argument("--no-ui", action="store_true", help="Do not start the browser UI dev/preview server.")
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


def write_default_config(
    path: Path,
    *,
    self_peer_id: str,
    mode: str,
    port: int,
    workspace_id: str,
    workspace_root: Path,
) -> None:
    if path.exists():
        return
    config = {
        "selfPeerId": self_peer_id,
        "mode": mode,
        "listen": {"host": "127.0.0.1", "port": port},
        "workspace": {
            "workspaceId": workspace_id,
            "root": str(workspace_root),
            "statusPollIntervalMs": 1000,
        },
        "peers": [],
    }
    write_json_private(path, config)


def sync_collaborators(config_root: Path, config_paths: list[Path]) -> None:
    collaborators_path = config_root / "collaborators.json"
    if not collaborators_path.exists():
        return
    with collaborators_path.open("r", encoding="utf-8") as f:
        collaborators = json.load(f)
    if not isinstance(collaborators, list):
        raise ValueError(f"{collaborators_path} must contain a JSON list")
    for config_path in config_paths:
        if not config_path.exists():
            continue
        with config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)
        if not isinstance(config, dict):
            raise ValueError(f"{config_path} must contain a JSON object")
        config["peers"] = sorted([dict(item) for item in collaborators], key=lambda item: str(item.get("peerId", "")))
        write_json_private(config_path, config)


def sync_local_hub_registration(client_config: Path, *, hub_port: int) -> None:
    if not client_config.exists():
        return
    with client_config.open("r", encoding="utf-8") as f:
        config = json.load(f)
    if not isinstance(config, dict):
        raise ValueError(f"{client_config} must contain a JSON object")
    hub = dict(config.get("hub", {})) if isinstance(config.get("hub", {}), dict) else {}
    hub["url"] = f"ws://127.0.0.1:{hub_port}/ws"
    hub.setdefault("heartbeatIntervalMs", 1000)
    config["hub"] = hub
    write_json_private(client_config, config)


def write_json_private(path: Path, value: dict[str, Any]) -> None:
    ensure_private_dir(path.parent)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)
    os.chmod(path, 0o600)


def start_service(repo_root: Path, command: str, config: Path) -> StartedProcess:
    return StartedProcess(
        name=f"griplab {command}",
        process=subprocess.Popen([
            "uv",
            "run",
            "--with-editable",
            "services/filedelta",
            "--with-editable",
            "services/diffstream",
            "--with-editable",
            "services/griplab_service",
            "griplab",
            command,
            "--config",
            str(config),
        ], cwd=repo_root),
    )


def start_ui(repo_root: Path, *, service: bool, prod: bool, service_port: int, hub_route: bool = False) -> StartedProcess:
    env = ui_env(service=service, service_port=service_port, hub_route=hub_route)
    if prod:
        cmd = ["npm", "run", "preview", "--", "--host", "127.0.0.1"]
        name = "vite preview"
    else:
        cmd = ["npm", "run", "dev", "--", "--host", "127.0.0.1"]
        name = "vite dev"
    return StartedProcess(name=name, process=subprocess.Popen(cmd, cwd=repo_root, env=env))


def ui_env(*, service: bool, service_port: int, hub_route: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    if service:
        env["VITE_GL_DATA"] = "service"
        env["VITE_GL_SERVICE_URL"] = f"ws://127.0.0.1:{service_port}/ws"
        if hub_route:
            env["VITE_GL_HUB_ROUTE"] = "1"
            env["VITE_GL_HUB_PRESENCE"] = "1"
    else:
        env["VITE_GL_DATA"] = "mock"
    return env


def run_checked(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def stop_processes(processes: list[StartedProcess]) -> None:
    for item in processes:
        if item.process.poll() is None:
            item.process.terminate()
    deadline = time.time() + 5
    for item in processes:
        while item.process.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        if item.process.poll() is None:
            item.process.kill()
    processes.clear()


def print_startup_summary(config_root: Path, client_config: Path, hub_config: Path, processes: list[StartedProcess]) -> None:
    print(json.dumps({
        "ok": True,
        "configRoot": str(config_root),
        "clientConfig": str(client_config),
        "hubConfig": str(hub_config),
        "started": [item.name for item in processes],
    }, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

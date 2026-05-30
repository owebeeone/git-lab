"""SSH probe helpers for remote peer onboarding."""

from __future__ import annotations

import shlex
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SshTarget:
    user: str
    host: str
    port: int = 22

    def destination(self) -> str:
        return f"{self.user}@{self.host}"


@dataclass
class BootstrapProcess:
    bootstrap_id: str
    peer_id: str
    local_port: int
    remote_port: int
    process: subprocess.Popen[bytes]


class EphemeralBootstrapManager:
    """Owns SSH remote-process and port-forward lifetimes."""

    def __init__(self) -> None:
        self._index = 0
        self.processes: dict[str, BootstrapProcess] = {}

    def bootstrap(self, payload: dict[str, Any]) -> dict[str, object]:
        self._index += 1
        bootstrap_id = f"boot-{self._index:06d}"
        peer_id = str(payload.get("peerId", bootstrap_id))
        remote_port = int(payload.get("remotePort", 3141))
        local_port = int(payload.get("localPort", 0)) or allocate_local_port()
        location = str(payload.get("location", "."))
        remote_command = str(payload.get("remoteCommand", default_remote_client_command()))
        try:
            target = parse_ssh_target(str(payload.get("sshAddress", "")))
            ssh_command = ssh_base_command(payload)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        tunnel = f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}"
        command = f"cd {shlex.quote(location)} && exec {remote_command}"
        process = subprocess.Popen(
            [
                *ssh_command,
                "-o",
                "ExitOnForwardFailure=yes",
                "-L",
                tunnel,
                target.destination(),
                command,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if process.poll() is not None:
            return {
                "ok": False,
                "error": f"ssh bootstrap exited {process.returncode}",
            }
        self.processes[bootstrap_id] = BootstrapProcess(
            bootstrap_id=bootstrap_id,
            peer_id=peer_id,
            local_port=local_port,
            remote_port=remote_port,
            process=process,
        )
        return {
            "ok": True,
            "bootstrapId": bootstrap_id,
            "peerId": peer_id,
            "localUrl": f"http://127.0.0.1:{local_port}",
            "localPort": local_port,
            "remotePort": remote_port,
            "mode": "ephemeral",
        }

    def stop(self, bootstrap_id: str) -> bool:
        item = self.processes.pop(bootstrap_id, None)
        if item is None:
            return False
        item.process.terminate()
        try:
            item.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            item.process.kill()
            item.process.wait(timeout=2)
        return True

    def close(self) -> None:
        for bootstrap_id in list(self.processes):
            self.stop(bootstrap_id)


def parse_ssh_target(value: str) -> SshTarget:
    if "@" not in value:
        raise ValueError("ssh target must be user@host or user@host:port")
    user, host_port = value.rsplit("@", 1)
    if not user or not host_port:
        raise ValueError("ssh target must include user and host")
    host = host_port
    port = 22
    if ":" in host_port:
        host, port_value = host_port.rsplit(":", 1)
        port = int(port_value)
    if not host:
        raise ValueError("ssh target host must not be empty")
    if port <= 0 or port > 65535:
        raise ValueError("ssh target port must be between 1 and 65535")
    return SshTarget(user=user, host=host, port=port)


def probe_peer(payload: dict[str, Any], *, timeout: float = 8) -> dict[str, object]:
    ssh_address = str(payload.get("sshAddress", ""))
    location = str(payload.get("location", "."))
    target = parse_ssh_target(ssh_address)
    command = remote_probe_command(location)
    try:
        cmd = [*ssh_base_command(payload), target.destination(), command]
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ssh probe timed out"}
    if result.returncode != 0:
        return {
            "ok": False,
            "error": result.stderr.strip() or result.stdout.strip() or f"ssh exited {result.returncode}",
        }
    lines = result.stdout.splitlines()
    os_name = lines[0].strip().lower() if len(lines) > 0 else "unknown"
    git_path = lines[1].strip() if len(lines) > 1 else ""
    shell = lines[2].strip() if len(lines) > 2 else ""
    workspace_exists = lines[3].strip() == "exists" if len(lines) > 3 else False
    return {
        "ok": True,
        "sshAddress": ssh_address,
        "os": normalize_os(os_name),
        "shells": [Path(shell).name] if shell else [],
        "git": bool(git_path),
        "workspace": {
            "root": location,
            "exists": workspace_exists,
        },
    }


def remote_probe_command(location: str) -> str:
    quoted = shlex.quote(location)
    return " ; ".join([
        "uname -s",
        "command -v git || true",
        'printf "%s\\n" "$SHELL"',
        f"test -d {quoted} && echo exists || echo missing",
    ])


def ssh_base_command(payload: dict[str, Any]) -> list[str]:
    target = parse_ssh_target(str(payload.get("sshAddress", "")))
    ssh = shutil.which("ssh")
    if ssh is None:
        raise ValueError("ssh executable was not found")
    cmd = [
        ssh,
        "-F",
        "/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "ConnectTimeout=5",
        "-p",
        str(target.port),
    ]
    known_hosts = payload.get("knownHostsFile")
    if known_hosts:
        cmd.extend([
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={known_hosts}",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
        ])
    identity_file = payload.get("identityFile")
    if identity_file:
        cmd.extend(["-i", str(identity_file)])
    return cmd


def allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def default_remote_client_command() -> str:
    return "griplab client --config .grip-lab/client.json"


def normalize_os(value: str) -> str:
    if value.startswith("darwin"):
        return "macos"
    if value.startswith("linux"):
        return "linux"
    if value.startswith(("mingw", "msys", "cygwin")):
        return "windows"
    return value or "unknown"

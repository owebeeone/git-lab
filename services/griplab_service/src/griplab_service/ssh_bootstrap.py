"""SSH probe helpers for remote peer onboarding."""

from __future__ import annotations

import shlex
import shutil
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
    ssh = shutil.which("ssh")
    if ssh is None:
        return {"ok": False, "error": "ssh executable was not found"}
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
    cmd.extend([target.destination(), command])
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


def normalize_os(value: str) -> str:
    if value.startswith("darwin"):
        return "macos"
    if value.startswith("linux"):
        return "linux"
    if value.startswith(("mingw", "msys", "cygwin")):
        return "windows"
    return value or "unknown"

"""SSH probe helpers for remote peer onboarding."""

from __future__ import annotations

import shlex
import shutil
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


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


@dataclass(frozen=True)
class ForwardPlan:
    peer_id: str
    local_peer_port: int
    remote_hub_port: int
    remote_client_port: int
    hub_host: str
    hub_port: int

    def to_json(self) -> dict[str, object]:
        return {
            "peerId": self.peer_id,
            "localPeerPort": self.local_peer_port,
            "remoteHubPort": self.remote_hub_port,
            "remoteClientPort": self.remote_client_port,
            "hubUrl": f"ws://127.0.0.1:{self.remote_hub_port}/ws",
            "localPeerUrl": f"http://127.0.0.1:{self.local_peer_port}",
        }


@dataclass(frozen=True)
class RemotePrepareResult:
    ok: bool
    peer_id: str
    diagnostics: dict[str, object]
    forward: dict[str, object]
    error: str | None = None

    def to_json(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": self.ok,
            "peerId": self.peer_id,
            "diagnostics": self.diagnostics,
            "forward": self.forward,
        }
        if self.error:
            result["error"] = self.error
        return result


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


class HubBootstrapWorker:
    """Hub-side bootstrap coordinator for prepare-only remote client setup."""

    def __init__(self, *, hub_host: str = "127.0.0.1", hub_port: int = 3140) -> None:
        self.hub_host = hub_host
        self.hub_port = hub_port
        self.results: dict[str, dict[str, object]] = {}

    def prepare(self, payload: dict[str, Any]) -> dict[str, object]:
        result = prepare_remote_client(payload, hub_host=self.hub_host, hub_port=self.hub_port)
        peer_id = str(result.get("peerId", payload.get("peerId", "")))
        if peer_id:
            self.results[peer_id] = result
        return result

    def health(self, peer_id: str) -> dict[str, object] | None:
        return self.results.get(peer_id)


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


def prepare_remote_client(
    payload: dict[str, Any],
    *,
    hub_host: str = "127.0.0.1",
    hub_port: int = 3140,
    timeout: float = 15,
) -> dict[str, object]:
    """Copy/update remote griplab config without starting the client process."""

    peer_id = str(payload.get("peerId", "")).strip() or "peer"
    try:
        target = parse_ssh_target(str(payload.get("sshAddress", "")))
        plan = ForwardPlan(
            peer_id=peer_id,
            local_peer_port=int(payload.get("localPeerPort", 0)) or allocate_local_port(),
            remote_hub_port=int(payload.get("remoteHubPort", 43140)),
            remote_client_port=int(payload.get("remoteClientPort", 3141)),
            hub_host=hub_host,
            hub_port=hub_port,
        )
        diagnostics = diagnose_peer(payload, timeout=timeout)
        if not diagnostics.get("ok", False):
            return RemotePrepareResult(False, peer_id, diagnostics, plan.to_json(), str(diagnostics.get("error", ""))).to_json()
        remote_home = str(payload.get("remoteConfigDir", "~/.griplab")) or "~/.griplab"
        _run_ssh(payload, f"mkdir -p {shlex.quote(remote_home)} && chmod 700 {shlex.quote(remote_home)}", timeout=timeout)
        with secure_temp_dir() as temp_dir:
            client_json = remote_client_config(payload, plan)
            forward_json = plan.to_json()
            payload_json = selected_client_payload(diagnostics)
            write_json(temp_dir / "client.json", client_json)
            write_json(temp_dir / "forward.json", forward_json)
            write_json(temp_dir / "client_payload.json", payload_json)
            for filename in ("client.json", "forward.json", "client_payload.json"):
                _run_scp(payload, temp_dir / filename, f"{target.destination()}:{remote_home}/{filename}", timeout=timeout)
        return RemotePrepareResult(True, peer_id, diagnostics, plan.to_json()).to_json()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        forward = plan.to_json() if "plan" in locals() else {}
        return RemotePrepareResult(False, peer_id, {}, forward, str(exc)).to_json()


def diagnose_peer(payload: dict[str, Any], *, timeout: float = 8) -> dict[str, object]:
    try:
        fingerprint = _run_ssh(payload, shell_fingerprint_command(), timeout=timeout).stdout.strip()
        shell_kind = classify_shell_fingerprint(fingerprint)
        diagnostics = _run_ssh(payload, remote_diagnostics_command(str(payload.get("location", "."))), timeout=timeout).stdout
    except (ValueError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}
    parsed = parse_remote_diagnostics(diagnostics)
    parsed["shell"] = {"kind": shell_kind, "raw": fingerprint}
    parsed["ok"] = bool(parsed["python"]["ok"] and parsed["uv"]["ok"] and parsed["git"]["ok"] and parsed["node"]["ok"])
    return parsed


def shell_fingerprint_command() -> str:
    return 'echo "Linux: $SHELL | Win: %SHELL% / $env:SHELL"'


def classify_shell_fingerprint(output: str) -> str:
    if "$env:SHELL" not in output and "Win:" in output:
        return "powershell"
    if "%SHELL%" not in output and "Win:" in output:
        return "cmd"
    if "$SHELL" not in output and "Linux:" in output:
        return "posix"
    return "unknown"


def remote_diagnostics_command(location: str) -> str:
    quoted = shlex.quote(location)
    return " ; ".join([
        'printf "os=%s\\n" "$(uname -s 2>/dev/null || echo unknown)"',
        'printf "arch=%s\\n" "$(uname -m 2>/dev/null || echo unknown)"',
        'printf "python=%s\\n" "$(command -v python3 || command -v python || true)"',
        'printf "uv=%s\\n" "$(command -v uv || true)"',
        'printf "git=%s\\n" "$(command -v git || true)"',
        'printf "node=%s\\n" "$(command -v node || true)"',
        'printf "npm=%s\\n" "$(command -v npm || true)"',
        f"test -d {quoted} && echo workspace=exists || echo workspace=missing",
        "test -w . && echo writable=yes || echo writable=no",
    ])


def parse_remote_diagnostics(output: str) -> dict[str, object]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return {
        "os": normalize_os(values.get("os", "")),
        "arch": values.get("arch", "unknown") or "unknown",
        "python": tool_check("python", values.get("python", "")),
        "uv": tool_check("uv", values.get("uv", "")),
        "git": tool_check("git", values.get("git", "")),
        "node": tool_check("node", values.get("node", "")),
        "npm": tool_check("npm", values.get("npm", "")),
        "workspace": {"status": values.get("workspace", "unknown")},
        "writable": values.get("writable") == "yes",
    }


def tool_check(name: str, value: str) -> dict[str, object]:
    return {
        "name": name,
        "ok": bool(value),
        "path": value or None,
        "summary": f"{name} found" if value else f"{name} missing",
    }


def remote_client_config(payload: dict[str, Any], plan: ForwardPlan) -> dict[str, object]:
    return {
        "selfPeerId": plan.peer_id,
        "mode": "client",
        "listen": {"host": "127.0.0.1", "port": plan.remote_client_port},
        "hub": {"url": f"ws://127.0.0.1:{plan.remote_hub_port}/ws"},
        "workspace": {
            "workspaceId": str(payload.get("workspaceId", f"{plan.peer_id}-workspace")),
            "root": str(payload.get("location", ".")),
        },
        "peers": [],
    }


def selected_client_payload(diagnostics: dict[str, object]) -> dict[str, object]:
    return {
        "kind": "griplab-client-placeholder",
        "os": diagnostics.get("os", "unknown"),
        "arch": diagnostics.get("arch", "unknown"),
        "updatedBy": "hub-bootstrap",
    }


def build_tunnel_command(payload: dict[str, Any], plan: ForwardPlan) -> list[str]:
    target = parse_ssh_target(str(payload.get("sshAddress", "")))
    return [
        *ssh_base_command(payload),
        "-o",
        "ExitOnForwardFailure=yes",
        "-N",
        "-R",
        f"127.0.0.1:{plan.remote_hub_port}:{plan.hub_host}:{plan.hub_port}",
        "-L",
        f"127.0.0.1:{plan.local_peer_port}:127.0.0.1:{plan.remote_client_port}",
        target.destination(),
    ]


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


def scp_base_command(payload: dict[str, Any]) -> list[str]:
    target = parse_ssh_target(str(payload.get("sshAddress", "")))
    scp = shutil.which("scp")
    if scp is None:
        raise ValueError("scp executable was not found")
    cmd = [
        scp,
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
        "-P",
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


@contextmanager
def secure_temp_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="griplab-bootstrap-") as name:
        path = Path(name)
        path.chmod(0o700)
        yield path


def write_json(path: Path, value: Any) -> None:
    import json

    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_ssh(payload: dict[str, Any], remote_command: str, *, timeout: float) -> subprocess.CompletedProcess[str]:
    target = parse_ssh_target(str(payload.get("sshAddress", "")))
    result = subprocess.run(
        [*ssh_base_command(payload), target.destination(), remote_command],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise subprocess.SubprocessError(result.stderr.strip() or result.stdout.strip() or f"ssh exited {result.returncode}")
    return result


def _run_scp(payload: dict[str, Any], source: Path, destination: str, *, timeout: float) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [*scp_base_command(payload), str(source), destination],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise subprocess.SubprocessError(result.stderr.strip() or result.stdout.strip() or f"scp exited {result.returncode}")
    return result

"""Ephemeral localhost sshd harness for integration tests."""

from __future__ import annotations

import os
import pwd
import shlex
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .repo_env import CLASSIC, RepoDefinition


class SshTestEnvError(RuntimeError):
    """Raised when the private sshd test environment cannot be started."""


@dataclass(frozen=True)
class SshCommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class SshTestPeer:
    host: str
    port: int
    user: str
    identity_file: Path
    known_hosts_file: Path
    workspace_root: Path
    root_repo: Path
    repos: dict[str, Path]
    sshd_config: Path
    sshd_pid_file: Path
    sshd_log: Path
    ssh_command: tuple[str, ...]

    def destination(self) -> str:
        return f"{self.user}@{self.host}"


@dataclass(frozen=True)
class SshTooling:
    sshd: Path
    ssh: Path
    ssh_keygen: Path
    git: Path


def find_ssh_tooling() -> SshTooling | None:
    sshd = shutil.which("sshd") or ("/usr/sbin/sshd" if Path("/usr/sbin/sshd").exists() else None)
    ssh = shutil.which("ssh")
    ssh_keygen = shutil.which("ssh-keygen")
    git = shutil.which("git")
    if not sshd or not ssh or not ssh_keygen or not git:
        return None
    return SshTooling(
        sshd=Path(sshd),
        ssh=Path(ssh),
        ssh_keygen=Path(ssh_keygen),
        git=Path(git),
    )


def allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SshTestEnvironment:
    def __init__(
        self,
        root: Path,
        *,
        tooling: SshTooling | None = None,
        repo_definition: RepoDefinition = CLASSIC,
    ) -> None:
        self.root = root
        self.repo_definition = repo_definition
        found = tooling or find_ssh_tooling()
        if found is None:
            raise SshTestEnvError("sshd, ssh, ssh-keygen, and git are required")
        self.tooling = found
        self.peer: SshTestPeer | None = None
        self._process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> SshTestPeer:
        return self.start()

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.stop()

    def start(self) -> SshTestPeer:
        if self.peer is not None:
            return self.peer

        ssh_root = self.root / "ssh"
        ssh_root.mkdir(parents=True, mode=0o700)
        os.chmod(ssh_root, 0o700)
        built_workspace = self.repo_definition.build(self.root / "workspace", git=self.tooling.git)

        user = pwd.getpwuid(os.getuid()).pw_name
        port = allocate_local_port()
        host_key = ssh_root / "ssh_host_ed25519_key"
        client_key = ssh_root / "client_ed25519"
        authorized_keys = ssh_root / "authorized_keys"
        known_hosts = ssh_root / "known_hosts"
        config = ssh_root / "sshd_config"
        pid_file = ssh_root / "sshd.pid"
        log = ssh_root / "sshd.log"

        self._keygen(host_key)
        self._keygen(client_key)
        authorized_keys.write_text((client_key.with_suffix(".pub")).read_text(encoding="utf-8"), encoding="utf-8")
        self._write_known_hosts(known_hosts, host_key.with_suffix(".pub"), port)
        os.chmod(authorized_keys, 0o600)
        os.chmod(client_key, 0o600)
        os.chmod(host_key, 0o600)

        self._write_sshd_config(config, host_key, authorized_keys, port, user)
        self._validate_config(config)

        peer = SshTestPeer(
            host="127.0.0.1",
            port=port,
            user=user,
            identity_file=client_key,
            known_hosts_file=known_hosts,
            workspace_root=built_workspace.workspace_root,
            root_repo=built_workspace.root_repo,
            repos=built_workspace.repos,
            sshd_config=config,
            sshd_pid_file=pid_file,
            sshd_log=log,
            ssh_command=self._base_ssh_command(client_key, known_hosts, port),
        )

        try:
            self._process = subprocess.Popen(
                [str(self.tooling.sshd), "-D", "-f", str(config), "-E", str(log)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.peer = peer
            self._wait_ready(peer)
            return peer
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
            self._process = None
        self.peer = None

    def run_ssh(
        self,
        remote_command: str,
        *,
        timeout: float = 5,
        identity_file: Path | None = None,
        known_hosts_file: Path | None = None,
    ) -> SshCommandResult:
        if self.peer is None:
            raise SshTestEnvError("ssh test environment has not started")
        cmd = list(self.peer.ssh_command)
        if identity_file is not None:
            cmd[cmd.index(str(self.peer.identity_file))] = str(identity_file)
        if known_hosts_file is not None:
            old = f"UserKnownHostsFile={self.peer.known_hosts_file}"
            cmd[cmd.index(old)] = f"UserKnownHostsFile={known_hosts_file}"
        cmd.extend([self.peer.destination(), remote_command])
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
        return SshCommandResult(result.returncode, result.stdout, result.stderr)

    def _keygen(self, key_path: Path) -> None:
        subprocess.run(
            [str(self.tooling.ssh_keygen), "-q", "-t", "ed25519", "-N", "", "-f", str(key_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _write_known_hosts(self, known_hosts: Path, host_pub_key: Path, port: int) -> None:
        parts = host_pub_key.read_text(encoding="utf-8").strip().split()
        known_hosts.write_text(f"[127.0.0.1]:{port} {parts[0]} {parts[1]}\n", encoding="utf-8")
        os.chmod(known_hosts, 0o600)

    def _write_sshd_config(
        self,
        path: Path,
        host_key: Path,
        authorized_keys: Path,
        port: int,
        user: str,
    ) -> None:
        lines = [
            f"HostKey {host_key}",
            f"PidFile {path.parent / 'sshd.pid'}",
            f"Port {port}",
            "ListenAddress 127.0.0.1",
            f"AuthorizedKeysFile {authorized_keys}",
            "PasswordAuthentication no",
            "KbdInteractiveAuthentication no",
            "ChallengeResponseAuthentication no",
            "PubkeyAuthentication yes",
            "PermitRootLogin no",
            f"AllowUsers {user}",
            "StrictModes no",
            "UsePAM no",
            "LogLevel ERROR",
        ]
        sftp = Path("/usr/libexec/sftp-server")
        if sftp.exists():
            lines.append(f"Subsystem sftp {sftp}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _validate_config(self, config: Path) -> None:
        self._run([str(self.tooling.sshd), "-f", str(config), "-t"])

    def _run(self, cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, text=True, capture_output=True, timeout=10, check=True)

    def _base_ssh_command(self, client_key: Path, known_hosts: Path, port: int) -> tuple[str, ...]:
        return (
            str(self.tooling.ssh),
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
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={known_hosts}",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-i",
            str(client_key),
            "-p",
            str(port),
        )

    def _wait_ready(self, peer: SshTestPeer) -> None:
        deadline = time.monotonic() + 5
        last: SshCommandResult | None = None
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                break
            last = self.run_ssh("true", timeout=2)
            if last.returncode == 0:
                return
            time.sleep(0.1)
        log = peer.sshd_log.read_text(encoding="utf-8") if peer.sshd_log.exists() else ""
        detail = last.stderr if last else log
        raise SshTestEnvError(f"private sshd did not become ready: {detail}\n{log}")

def shell_quote(path: Path | str) -> str:
    return shlex.quote(str(path))

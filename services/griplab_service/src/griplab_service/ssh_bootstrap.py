"""SSH probe helpers for remote peer onboarding."""

from __future__ import annotations

import shlex
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
import base64
import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


PYTHON_LAUNCHER = "import base64,sys;exec(base64.b64decode(sys.argv[1]))"
REMOTE_PYTHON_CANDIDATES = ("python", "python3", "py -3")


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
    remote_hub_port: int
    log_stdout: str
    log_stderr: str
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
    client_payload: dict[str, object] | None = None
    error: str | None = None

    def to_json(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": self.ok,
            "peerId": self.peer_id,
            "diagnostics": self.diagnostics,
            "forward": self.forward,
        }
        if self.client_payload is not None:
            result["clientPayload"] = self.client_payload
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
        remote_hub_port = int(payload.get("remoteHubPort", 43140))
        hub_host = str(payload.get("hubHost", "127.0.0.1"))
        hub_port = int(payload.get("hubPort", 3140))
        location = str(payload.get("location", "."))
        config_path = remote_client_config_path(payload)
        remote_command = str(payload.get("remoteCommand", ""))
        try:
            target = parse_ssh_target(str(payload.get("sshAddress", "")))
            ssh_command = ssh_base_command(payload)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        log_root = str(payload.get("remoteLogDir", remote_log_dir(payload)))
        log_stdout = f"{log_root}/{peer_id}.out"
        log_stderr = f"{log_root}/{peer_id}.err"
        if remote_command:
            command = remote_start_command(
                location,
                remote_command,
                log_root,
                log_stdout,
                log_stderr,
            )
        else:
            command = remote_client_start_python_command(
                python_command=str(payload.get("remotePythonCommand", "python")),
                uv_command=str(payload.get("remoteUvCommand", "uv")),
                location=location,
                config_path=config_path,
                payload_dir=remote_client_payload_dir(payload),
                log_root=log_root,
                log_stdout=log_stdout,
                log_stderr=log_stderr,
                pid_file=remote_client_pid_file(payload),
            )
        process = subprocess.Popen(
            build_start_command(
                ssh_command,
                target.destination(),
                ForwardPlan(
                    peer_id=peer_id,
                    local_peer_port=local_port,
                    remote_hub_port=remote_hub_port,
                    remote_client_port=remote_port,
                    hub_host=hub_host,
                    hub_port=hub_port,
                ),
                command,
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        started, stdout, stderr, error = wait_for_forwarded_health(
            process,
            local_port,
            require_http_health=not bool(remote_command),
        )
        if not started:
            logs = {
                "stdout": log_stdout,
                "stderr": log_stderr,
                "remote": remote_log_tails(payload, {"stdout": log_stdout, "stderr": log_stderr}),
                "sshStdout": decode_process_output(stdout),
                "sshStderr": decode_process_output(stderr),
            }
            return {
                "ok": False,
                "error": error or f"ssh bootstrap exited {process.returncode}",
                "health": process_health(False, error or f"ssh bootstrap exited {process.returncode}"),
                "logs": logs,
            }
        self.processes[bootstrap_id] = BootstrapProcess(
            bootstrap_id=bootstrap_id,
            peer_id=peer_id,
            local_port=local_port,
            remote_port=remote_port,
            remote_hub_port=remote_hub_port,
            log_stdout=log_stdout,
            log_stderr=log_stderr,
            process=process,
        )
        return {
            "ok": True,
            "bootstrapId": bootstrap_id,
            "peerId": peer_id,
            "localUrl": f"http://127.0.0.1:{local_port}",
            "localPort": local_port,
            "remotePort": remote_port,
            "remoteHubPort": remote_hub_port,
            "logs": {"stdout": log_stdout, "stderr": log_stderr},
            "health": process_health(True, "Remote process was started"),
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
    """Hub-side bootstrap coordinator for remote client setup and start."""

    def __init__(
        self,
        *,
        hub_host: str = "127.0.0.1",
        hub_port: int = 3140,
        log_root: Path | None = None,
    ) -> None:
        self.hub_host = hub_host
        self.hub_port = hub_port
        self.results: dict[str, dict[str, object]] = {}
        self.processes = EphemeralBootstrapManager()
        self.log_root = log_root

    def prepare(self, payload: dict[str, Any]) -> dict[str, object]:
        result = prepare_remote_client(payload, hub_host=self.hub_host, hub_port=self.hub_port)
        peer_id = str(result.get("peerId", payload.get("peerId", "")))
        if peer_id:
            self.results[peer_id] = result
        return result

    def bootstrap(self, payload: dict[str, Any]) -> dict[str, object]:
        peer_id = str(payload.get("peerId", "")).strip() or "peer"
        self._log(peer_id, {"event": "start", "payload": redacted_payload(payload)})
        prepare = self.prepare(payload)
        self._log(peer_id, {"event": "prepare", "result": prepare})
        if not prepare.get("ok", False):
            self.results[peer_id] = {
                **prepare,
                "status": "error",
                "summary": str(prepare.get("error", "remote preparation failed")),
            }
            return self.results[peer_id]
        forward = prepare.get("forward", {})
        start_payload = {
            **payload,
            "localPort": int(forward.get("localPeerPort", payload.get("localPort", 0))),
            "remotePort": int(forward.get("remoteClientPort", payload.get("remotePort", 3141))),
            "remoteHubPort": int(forward.get("remoteHubPort", payload.get("remoteHubPort", 43140))),
            "hubHost": self.hub_host,
            "hubPort": self.hub_port,
            "remoteLogDir": str(payload.get("remoteLogDir", remote_log_dir(payload))),
        }
        if "remoteCommand" in payload:
            start_payload["remoteCommand"] = str(payload["remoteCommand"])
        diagnostics = prepare.get("diagnostics", {})
        if isinstance(diagnostics, dict):
            python_command = diagnostics.get("pythonCommand")
            uv_command = diagnostics.get("uvCommand")
            if isinstance(python_command, str) and python_command:
                start_payload["remotePythonCommand"] = python_command
            if isinstance(uv_command, str) and uv_command:
                start_payload["remoteUvCommand"] = uv_command
        start = self.processes.bootstrap(start_payload)
        self._log(peer_id, {"event": "start-result", "result": start})
        self.results[peer_id] = {
            **prepare,
            "start": start,
            "status": "starting" if start.get("ok", False) else "error",
            "summary": "Remote client start issued" if start.get("ok", False) else str(start.get("error", "remote start failed")),
        }
        return self.results[peer_id]

    def health(self, peer_id: str) -> dict[str, object] | None:
        return self.results.get(peer_id)

    def close(self) -> None:
        self.processes.close()

    def _log(self, peer_id: str, event: dict[str, object]) -> None:
        if self.log_root is None:
            return
        self.log_root.mkdir(parents=True, exist_ok=True)
        path = self.log_root / f"{peer_id}.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time() * 1000), **event}, sort_keys=True))
            f.write("\n")


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
    diagnostics = diagnose_peer(payload, timeout=timeout)
    if not diagnostics.get("ok", False):
        return diagnostics
    workspace = diagnostics.get("workspace", {})
    shell = diagnostics.get("shell", {})
    git = diagnostics.get("git", {})
    return {
        "ok": True,
        "sshAddress": str(payload.get("sshAddress", "")),
        "os": diagnostics.get("os", "unknown"),
        "shells": [str(shell.get("kind", "unknown"))] if isinstance(shell, dict) else [],
        "git": bool(isinstance(git, dict) and git.get("ok")),
        "workspace": {
            "root": str(payload.get("location", ".")),
            "exists": bool(isinstance(workspace, dict) and workspace.get("status") == "exists"),
        },
        "diagnostics": diagnostics,
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
            return RemotePrepareResult(
                False,
                peer_id,
                diagnostics,
                plan.to_json(),
                error=str(diagnostics.get("error", "remote diagnostics failed")),
            ).to_json()
        remote_home = remote_config_dir(payload)
        python_command = str(diagnostics.get("pythonCommand", "python"))
        _run_remote_python(payload, python_command, REMOTE_ENSURE_DIRS_SCRIPT, {"paths": [remote_home]}, timeout=timeout)
        _run_remote_python(
            payload,
            python_command,
            REMOTE_STOP_CLIENT_SCRIPT,
            {"pidFile": remote_client_pid_file(payload)},
            timeout=timeout,
        )
        with secure_temp_dir() as temp_dir:
            payload_root = temp_dir / "client_payload"
            client_json = remote_client_config(payload, plan)
            forward_json = plan.to_json()
            write_json(temp_dir / "client.json", client_json)
            write_json(temp_dir / "forward.json", forward_json)
            payload_hash = build_local_client_payload(payload_root)
            payload_json = selected_client_payload(diagnostics, payload_hash)
            write_json(temp_dir / "client_payload.json", payload_json)
            for filename in ("client.json", "forward.json", "client_payload.json"):
                _run_scp(payload, temp_dir / filename, f"{target.destination()}:{remote_home}/{filename}", timeout=timeout)
            _run_remote_python(
                payload,
                python_command,
                REMOTE_REMOVE_PATHS_SCRIPT,
                {"paths": [remote_client_payload_dir(payload)]},
                timeout=timeout,
            )
            _run_scp_recursive(payload, payload_root, f"{target.destination()}:{remote_home}/", timeout=timeout)
        return RemotePrepareResult(True, peer_id, diagnostics, plan.to_json(), payload_json).to_json()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        forward = plan.to_json() if "plan" in locals() else {}
        return RemotePrepareResult(False, peer_id, {}, forward, error=str(exc)).to_json()


def diagnose_peer(payload: dict[str, Any], *, timeout: float = 8) -> dict[str, object]:
    try:
        fingerprint = _run_ssh(payload, shell_fingerprint_command(), timeout=timeout).stdout.strip()
        shell_kind = classify_shell_fingerprint(fingerprint)
        python_command, python_info = find_remote_python(payload, timeout=timeout)
        diagnostics = _run_remote_python(
            payload,
            python_command,
            REMOTE_DIAGNOSTICS_SCRIPT,
            {"location": str(payload.get("location", "."))},
            timeout=timeout,
        )
    except (ValueError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    parsed = parse_remote_diagnostics_json(diagnostics)
    parsed["shell"] = {"kind": shell_kind, "raw": fingerprint}
    parsed["pythonCommand"] = python_command
    parsed["pythonInfo"] = python_info
    parsed["ok"] = bool(
        parsed["python"]["ok"]
        and parsed["uv"]["ok"]
        and parsed["git"]["ok"]
        and parsed["node"]["ok"]
        and parsed["npm"]["ok"]
        and parsed["writable"]
    )
    if parsed["ok"]:
        parsed.pop("error", None)
    else:
        parsed["error"] = diagnostic_error(parsed)
    return parsed


def shell_fingerprint_command() -> str:
    return 'echo "Linux: $SHELL | Win: %SHELL% / $env:SHELL"'


def classify_shell_fingerprint(output: str) -> str:
    linux_value = ""
    if "Linux:" in output:
        linux_value = output.split("Linux:", 1)[1].split("| Win:", 1)[0].strip()
    if linux_value and "$SHELL" not in linux_value:
        return "posix"
    if "Win:" in output and "$env:SHELL" in output:
        return "cmd"
    if "Win:" in output and "%SHELL%" in output:
        return "powershell"
    return "unknown"


REMOTE_PYTHON_INFO_SCRIPT = r"""
import base64
import json
import os
import platform
import sys

print(json.dumps({
    "ok": True,
    "executable": sys.executable,
    "version": platform.python_version(),
    "osName": os.name,
}))
"""


REMOTE_DIAGNOSTICS_SCRIPT = r"""
import base64
import json
import os
import platform
import shutil
import sys
from pathlib import Path

payload = json.loads(base64.b64decode(sys.argv[2]).decode("utf-8"))
location = str(payload.get("location", "."))
workspace = Path(location)
existed = workspace.exists()
writable = False
write_error = ""
try:
    workspace.mkdir(parents=True, exist_ok=True)
    probe = workspace / ".griplab-write-test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    writable = True
except Exception as exc:
    write_error = str(exc)

home = Path.home()
search_dirs = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item]
search_dirs.extend([
    str(home / ".local" / "bin"),
    str(home / ".cargo" / "bin"),
    str(home / ".asdf" / "shims"),
    str(home / ".asdf" / "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
])
if os.name == "nt":
    local_app = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    search_dirs.extend([
        str(home / ".local" / "bin"),
        str(local_app / "Microsoft" / "WindowsApps"),
        str(program_files / "nodejs"),
        str(program_files / "Git" / "cmd"),
    ])
    search_dirs.extend(str(path) for path in local_app.glob("Programs/Python/Python*/Scripts"))
    search_dirs.extend(str(path) for path in local_app.glob("Programs/Python/Python*"))
seen = set()
search_path = os.pathsep.join(item for item in search_dirs if item and not (item in seen or seen.add(item)))

def tool(name):
    path = shutil.which(name, path=search_path)
    if not path and os.name == "nt" and not name.lower().endswith(".exe"):
        path = shutil.which(f"{name}.exe", path=search_path)
    return {
        "name": name,
        "ok": bool(path),
        "path": path,
        "summary": f"{name} found" if path else f"{name} missing",
    }

python = {
    "name": "python",
    "ok": True,
    "path": sys.executable,
    "summary": "python found",
}
uv = tool("uv")
git = tool("git")
node = tool("node")
npm = tool("npm")
print(json.dumps({
    "os": platform.system().lower() or os.name,
    "arch": platform.machine() or "unknown",
    "python": python,
    "uv": uv,
    "git": git,
    "node": node,
    "npm": npm,
    "uvCommand": uv["path"] or "uv",
    "workspace": {
        "status": "exists" if existed else ("created" if workspace.exists() else "missing"),
        "root": location,
    },
    "writable": writable,
    "writeError": write_error,
}))
"""


REMOTE_ENSURE_DIRS_SCRIPT = r"""
import base64
import json
import os
import sys
from pathlib import Path

payload = json.loads(base64.b64decode(sys.argv[2]).decode("utf-8"))
for raw in payload.get("paths", []):
    path = Path(str(raw))
    path.mkdir(parents=True, exist_ok=True)
    try:
        if os.name != "nt":
            os.chmod(path, 0o700)
    except OSError:
        pass
print(json.dumps({"ok": True}))
"""


REMOTE_REMOVE_PATHS_SCRIPT = r"""
import base64
import json
import shutil
import sys
import time
from pathlib import Path

payload = json.loads(base64.b64decode(sys.argv[2]).decode("utf-8"))
for raw in payload.get("paths", []):
    path = Path(str(raw))
    for attempt in range(10):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            break
        except FileNotFoundError:
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.5)
print(json.dumps({"ok": True}))
"""


REMOTE_STOP_CLIENT_SCRIPT = r"""
import base64
import json
import os
import signal
import sys
import time
from pathlib import Path

payload = json.loads(base64.b64decode(sys.argv[2]).decode("utf-8"))
pid_file = Path(str(payload.get("pidFile", "")))
if not pid_file.exists():
    print(json.dumps({"ok": True, "stopped": False, "reason": "pid-file-missing"}))
    raise SystemExit(0)
try:
    record = json.loads(pid_file.read_text(encoding="utf-8"))
except Exception:
    record = {}

def terminate(pid):
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False

pids = [record.get("childPid"), record.get("wrapperPid")]
signalled = [pid for pid in pids if terminate(pid)]
if signalled:
    time.sleep(2)
try:
    pid_file.unlink(missing_ok=True)
except OSError:
    pass
print(json.dumps({"ok": True, "stopped": bool(signalled), "pids": signalled}))
"""


REMOTE_LOG_TAIL_SCRIPT = r"""
import base64
import json
import sys
from pathlib import Path

payload = json.loads(base64.b64decode(sys.argv[2]).decode("utf-8"))
line_count = int(payload.get("lines", 120))
result = {}
for name, raw in payload.get("paths", {}).items():
    path = Path(str(raw))
    if not path.exists():
        result[name] = {"path": str(path), "ok": True, "text": "<missing>"}
        continue
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        result[name] = {"path": str(path), "ok": True, "text": "\n".join(text.splitlines()[-line_count:])}
    except Exception as exc:
        result[name] = {"path": str(path), "ok": False, "error": str(exc)}
print(json.dumps(result))
"""


REMOTE_CLIENT_START_SCRIPT = r"""
import base64
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

payload = json.loads(base64.b64decode(sys.argv[2]).decode("utf-8"))
payload_dir = Path(str(payload["payloadDir"]))
config_path = str(payload["configPath"])
log_root = Path(str(payload["logRoot"]))
log_stdout = Path(str(payload["logStdout"]))
log_stderr = Path(str(payload["logStderr"]))
pid_file = Path(str(payload["pidFile"]))
uv_command = str(payload.get("uvCommand") or "uv")
log_root.mkdir(parents=True, exist_ok=True)

def terminate_pid(pid):
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return

def stop_existing():
    if not pid_file.exists():
        return
    try:
        record = json.loads(pid_file.read_text(encoding="utf-8"))
    except Exception:
        record = {}
    terminate_pid(record.get("childPid"))
    terminate_pid(record.get("wrapperPid"))
    time.sleep(0.5)

try:
    stop_existing()
    out = log_stdout.open("ab")
    err = log_stderr.open("ab")
    command = [
        uv_command,
        "run",
        "--with-editable",
        "services/filedelta",
        "--with-editable",
        "services/diffstream",
        "--with-editable",
        "services/griplab_service",
        "griplab",
        "client",
        "--config",
        config_path,
    ]
    child = subprocess.Popen(command, cwd=str(payload_dir), stdout=out, stderr=err)
    pid_file.write_text(json.dumps({"wrapperPid": os.getpid(), "childPid": child.pid}) + "\n", encoding="utf-8")

    def handle_signal(signum, _frame):
        terminate_pid(child.pid)
        raise SystemExit(128 + int(signum))

    signal.signal(signal.SIGTERM, handle_signal)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, handle_signal)
    raise SystemExit(child.wait())
except Exception as exc:
    try:
        with log_stderr.open("ab") as err:
            err.write((f"bootstrap error: {exc}\n").encode("utf-8", errors="replace"))
    except Exception:
        pass
    raise
"""


def remote_diagnostics_command(location: str, *, shell_kind: str = "posix") -> str:
    _ = shell_kind
    return remote_python_command("python", REMOTE_DIAGNOSTICS_SCRIPT, {"location": location})


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


def parse_remote_diagnostics_json(output: dict[str, object] | str) -> dict[str, object]:
    if isinstance(output, dict):
        parsed = output
    else:
        parsed = json.loads(output)
    return {
        "os": normalize_os(str(parsed.get("os", ""))),
        "arch": str(parsed.get("arch", "unknown") or "unknown"),
        "python": parsed.get("python", tool_check("python", "")),
        "uv": parsed.get("uv", tool_check("uv", "")),
        "git": parsed.get("git", tool_check("git", "")),
        "node": parsed.get("node", tool_check("node", "")),
        "npm": parsed.get("npm", tool_check("npm", "")),
        "uvCommand": str(parsed.get("uvCommand", "uv")),
        "workspace": parsed.get("workspace", {"status": "unknown"}),
        "writable": bool(parsed.get("writable", False)),
        "writeError": str(parsed.get("writeError", "")),
    }


def diagnostic_error(parsed: dict[str, object]) -> str:
    missing = [
        name
        for name in ("python", "uv", "git", "node", "npm")
        if not (isinstance(parsed.get(name), dict) and parsed[name].get("ok"))  # type: ignore[index, union-attr]
    ]
    if missing:
        return "missing remote tools: " + ", ".join(missing)
    if not parsed.get("writable", False):
        detail = str(parsed.get("writeError", "")).strip()
        return "workspace is not writable" + (f": {detail}" if detail else "")
    return "remote diagnostics failed"


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


def selected_client_payload(diagnostics: dict[str, object], payload_hash: str) -> dict[str, object]:
    return {
        "kind": "griplab-client-placeholder",
        "os": diagnostics.get("os", "unknown"),
        "arch": diagnostics.get("arch", "unknown"),
        "payloadHash": payload_hash,
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


def build_start_command(
    ssh_command: list[str],
    destination: str,
    plan: ForwardPlan,
    remote_command: str,
) -> list[str]:
    return [
        *ssh_command,
        "-o",
        "ExitOnForwardFailure=yes",
        "-R",
        f"127.0.0.1:{plan.remote_hub_port}:{plan.hub_host}:{plan.hub_port}",
        "-L",
        f"127.0.0.1:{plan.local_peer_port}:127.0.0.1:{plan.remote_client_port}",
        destination,
        remote_command,
    ]


def remote_start_command(
    location: str,
    remote_command: str,
    log_root: str,
    log_stdout: str,
    log_stderr: str,
    *,
    stop_existing: str | None = None,
) -> str:
    parts = [
        f"mkdir -p {shlex.quote(log_root)}",
        f"cd {shlex.quote(location)}",
    ]
    if stop_existing:
        parts.append(stop_existing)
    parts.append(f"{remote_command} > {shlex.quote(log_stdout)} 2> {shlex.quote(log_stderr)}")
    return " && ".join(parts)


def remote_stop_client_command(config_path: str) -> str:
    script = r"""
import os
import signal
import subprocess
import sys
import time

target = sys.argv[1]
config_dir = os.path.dirname(target)
payload_dir = os.path.join(config_dir, "client_payload") if config_dir else ""
self_pid = os.getpid()

def process_rows():
    result = subprocess.run(["ps", "-eo", "pid=,ppid=,args="], text=True, capture_output=True, check=False)
    rows = {}
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 2)
        if len(parts) < 3:
            continue
        pid_text, ppid_text, command = parts
        try:
            pid = int(pid_text)
            ppid = int(ppid_text)
        except ValueError:
            continue
        rows[pid] = (ppid, command)
    return rows

def ancestors(rows):
    found = {self_pid}
    pid = rows.get(self_pid, (os.getppid(), ""))[0]
    while pid and pid not in found:
        found.add(pid)
        pid = rows.get(pid, (0, ""))[0]
    return found

def matching_roots(rows, skip):
    roots = set()
    needles = [value for value in (target, config_dir, payload_dir) if value]
    for pid, (_ppid, command) in rows.items():
        if pid in skip:
            continue
        if any(needle in command for needle in needles) and "client" in command and (
            "griplab" in command or "client_payload" in command
        ):
            roots.add(pid)
    return roots

def with_descendants(rows, roots, skip):
    children = {}
    for pid, (ppid, _command) in rows.items():
        children.setdefault(ppid, set()).add(pid)
    found = set()
    stack = list(roots)
    while stack:
        pid = stack.pop()
        if pid in found or pid in skip:
            continue
        found.add(pid)
        stack.extend(children.get(pid, set()))
    return found

rows = process_rows()
skip = ancestors(rows)
targets = with_descendants(rows, matching_roots(rows, skip), skip)
for pid in targets:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
time.sleep(0.5)
rows = process_rows()
skip = ancestors(rows)
for pid in with_descendants(rows, matching_roots(rows, skip), skip):
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
"""
    return " ".join([
        'PYTHON="$(command -v python3 || command -v python)"',
        "&&",
        '"$PYTHON"',
        "-c",
        shlex.quote(script),
        shlex.quote(config_path),
    ])


def remote_client_pid_file(payload: dict[str, Any]) -> str:
    return f"{remote_config_dir(payload).rstrip('/')}/client.pid.json"


def remote_client_start_python_command(
    *,
    python_command: str,
    uv_command: str,
    location: str,
    config_path: str,
    payload_dir: str,
    log_root: str,
    log_stdout: str,
    log_stderr: str,
    pid_file: str,
) -> str:
    return remote_python_command(
        python_command,
        REMOTE_CLIENT_START_SCRIPT,
        {
            "location": location,
            "configPath": config_path,
            "payloadDir": payload_dir,
            "logRoot": log_root,
            "logStdout": log_stdout,
            "logStderr": log_stderr,
            "pidFile": pid_file,
            "uvCommand": uv_command,
        },
    )


def runtime_health(diagnostics: dict[str, object]) -> dict[str, object]:
    checks = []
    for name in ("python", "uv", "git", "node", "npm"):
        value = diagnostics.get(name, {})
        ok = bool(isinstance(value, dict) and value.get("ok"))
        checks.append({
            "id": name,
            "status": "ok" if ok else "error",
            "summary": f"{name} found" if ok else f"{name} missing; install {name} on the collaborator host",
        })
    return {
        "status": "ok" if all(check["status"] == "ok" for check in checks) else "error",
        "checks": checks,
    }


def process_health(ok: bool, summary: str) -> dict[str, object]:
    return {
        "status": "ok" if ok else "error",
        "checks": [{"id": "process", "status": "ok" if ok else "error", "summary": summary}],
    }


def wait_for_forwarded_health(
    process: subprocess.Popen[bytes],
    local_port: int,
    *,
    timeout: float = 8.0,
    require_http_health: bool = True,
) -> tuple[bool, bytes | None, bytes | None, str | None]:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{local_port}/health"
    while time.time() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            return False, stdout, stderr, f"ssh bootstrap exited {process.returncode}"
        if require_http_health:
            try:
                with urllib.request.urlopen(url, timeout=0.25) as response:
                    if 200 <= response.status < 500:
                        return True, None, None, None
            except urllib.error.HTTPError as exc:
                if 200 <= exc.code < 500:
                    return True, None, None, None
            except (OSError, urllib.error.URLError):
                pass
        elif is_tcp_port_open(local_port):
            return True, None, None, None
        time.sleep(0.2)
    if process.poll() is not None:
        stdout, stderr = process.communicate(timeout=1)
        return False, stdout, stderr, f"ssh bootstrap exited {process.returncode}"
    return False, None, None, f"remote client did not become healthy on forwarded port {local_port}"


def is_tcp_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def decode_process_output(value: bytes | None) -> str:
    return (value or b"").decode("utf-8", errors="replace").strip()


def remote_log_tails(payload: dict[str, Any], paths: dict[str, str], *, timeout: float = 3, lines: int = 120) -> dict[str, object]:
    try:
        python_command = str(payload.get("remotePythonCommand", ""))
        if not python_command:
            python_command, _info = find_remote_python(payload, timeout=timeout)
        output = _run_remote_python(
            payload,
            python_command,
            REMOTE_LOG_TAIL_SCRIPT,
            {"paths": paths, "lines": int(lines)},
            timeout=timeout,
        )
        return output
    except (OSError, ValueError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
        return {
            name: {"path": path, "ok": False, "error": str(exc)}
            for name, path in paths.items()
        }


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
        cmd.extend(["-o", "IdentitiesOnly=yes"])
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
        cmd.extend(["-o", "IdentitiesOnly=yes"])
        cmd.extend(["-i", str(identity_file)])
    return cmd


def allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def remote_config_dir(payload: dict[str, Any]) -> str:
    configured = str(payload.get("remoteConfigDir", "")).strip()
    if configured:
        return configured
    location = str(payload.get("location", ".")).rstrip("/")
    return f"{location}/.griplab" if location else ".griplab"


def remote_log_dir(payload: dict[str, Any]) -> str:
    return f"{remote_config_dir(payload).rstrip('/')}/logs"


def remote_client_payload_dir(payload: dict[str, Any]) -> str:
    return f"{remote_config_dir(payload).rstrip('/')}/client_payload"


def remote_client_config_path(payload: dict[str, Any]) -> str:
    return f"{remote_config_dir(payload).rstrip('/')}/client.json"


def default_remote_client_command(config_path: str = ".griplab/client.json") -> str:
    payload_dir = f"{Path(config_path).parent}/client_payload" if not config_path.startswith("/") else f"{str(Path(config_path).parent)}/client_payload"
    return " ".join([
        "cd",
        shlex.quote(payload_dir),
        "&&",
        "uv",
        "run",
        "--with-editable",
        "services/filedelta",
        "--with-editable",
        "services/diffstream",
        "--with-editable",
        "services/griplab_service",
        "griplab",
        "client",
        "--config",
        shlex.quote(config_path),
    ])


def build_local_client_payload(destination: Path) -> str:
    services_root = local_griplab_root() / "services"
    payload_services = destination / "services"
    payload_services.mkdir(parents=True, exist_ok=True)
    for name in ("filedelta", "diffstream", "griplab_service"):
        shutil.copytree(
            services_root / name,
            payload_services / name,
            ignore=shutil.ignore_patterns(
                ".pytest_cache",
                "__pycache__",
                "*.pyc",
                "*.pyo",
                "*.egg-info",
            ),
        )
    return directory_hash(destination)


def directory_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def local_griplab_root() -> Path:
    return Path(__file__).resolve().parents[4]


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


def remote_python_command(python_command: str, script: str, payload: dict[str, object] | None = None) -> str:
    script_b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    payload_b64 = base64.b64encode(json.dumps(payload or {}).encode("utf-8")).decode("ascii")
    return f'{python_command} -c "{PYTHON_LAUNCHER}" {script_b64} {payload_b64}'


def find_remote_python(payload: dict[str, Any], *, timeout: float) -> tuple[str, dict[str, object]]:
    errors: list[str] = []
    for candidate in REMOTE_PYTHON_CANDIDATES:
        try:
            result = _run_remote_python(payload, candidate, REMOTE_PYTHON_INFO_SCRIPT, {}, timeout=timeout)
        except (OSError, ValueError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{candidate}: {exc}")
            continue
        if result.get("ok", False):
            return candidate, result
    raise subprocess.SubprocessError("python was not found on collaborator host; " + " | ".join(errors))


def _run_remote_python(
    payload: dict[str, Any],
    python_command: str,
    script: str,
    data: dict[str, object],
    *,
    timeout: float,
) -> dict[str, object]:
    result = _run_ssh(payload, remote_python_command(python_command, script, data), timeout=timeout)
    stdout = result.stdout.strip()
    if not stdout:
        return {}
    parsed = json.loads(stdout)
    if isinstance(parsed, dict):
        return parsed
    raise subprocess.SubprocessError("remote python returned non-object JSON")


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


def _run_scp_recursive(payload: dict[str, Any], source: Path, destination: str, *, timeout: float) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [*scp_base_command(payload), "-r", str(source), destination],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise subprocess.SubprocessError(result.stderr.strip() or result.stdout.strip() or f"scp exited {result.returncode}")
    return result


def redacted_payload(payload: dict[str, Any]) -> dict[str, object]:
    redacted = dict(payload)
    for key in ("identityFile", "knownHostsFile"):
        if key in redacted:
            redacted[key] = "<set>"
    return redacted

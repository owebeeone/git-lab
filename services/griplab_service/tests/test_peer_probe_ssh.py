import asyncio
from urllib.request import urlopen

import pytest
from aiohttp import ClientSession

from griplab_service.config import load_config
from griplab_service.local_client import LocalClientServer
from griplab_service.ssh_bootstrap import (
    ForwardPlan,
    allocate_local_port,
    build_tunnel_command,
    classify_shell_fingerprint,
    diagnose_peer,
    prepare_remote_client,
    parse_ssh_target,
)

from fixtures.ssh_env import SshTestEnvError, SshTestEnvironment, find_ssh_tooling, shell_quote
from test_local_client import write_config

pytestmark = pytest.mark.skipif(
    find_ssh_tooling() is None,
    reason="sshd, ssh, ssh-keygen, and git are required for SSH integration tests",
)


def test_parse_ssh_target() -> None:
    target = parse_ssh_target("alice@example.invalid:2222")
    assert target.user == "alice"
    assert target.host == "example.invalid"
    assert target.port == 2222
    assert target.destination() == "alice@example.invalid"


def test_shell_fingerprint_classification() -> None:
    assert classify_shell_fingerprint("Linux: /bin/zsh | Win: %SHELL% / $env:SHELL") == "posix"
    assert classify_shell_fingerprint("Linux: $SHELL | Win: %SHELL% / powershell-shell") == "powershell"
    assert classify_shell_fingerprint("Linux: $SHELL | Win: cmd-shell / $env:SHELL") == "cmd"


def test_tunnel_command_has_local_and_remote_forwards() -> None:
    plan = ForwardPlan(
        peer_id="fixture",
        local_peer_port=42001,
        remote_hub_port=43140,
        remote_client_port=3141,
        hub_host="127.0.0.1",
        hub_port=3140,
    )
    command = build_tunnel_command({"sshAddress": "alice@example.invalid:2222"}, plan)

    assert "-R" in command
    assert "127.0.0.1:43140:127.0.0.1:3140" in command
    assert "-L" in command
    assert "127.0.0.1:42001:127.0.0.1:3141" in command
    assert command[-1] == "alice@example.invalid"


def test_peer_probe_over_fixture_sshd(tmp_path) -> None:
    try:
        env = SshTestEnvironment(tmp_path / "ssh-fixture")
    except SshTestEnvError as exc:
        pytest.skip(str(exc))

    with env as peer:
        async def run() -> None:
            service_root = tmp_path / "service"
            service_root.mkdir()
            config = load_config(write_config(service_root, status_poll_interval_ms=1000))
            server = LocalClientServer(config)
            server.start()
            try:
                async with ClientSession() as session:
                    async with session.ws_connect(server.ws_url) as ws:
                        await ws.send_json({
                            "messageId": "m000001",
                            "kind": "request",
                            "method": "peer.probe",
                            "payload": {
                                "sshAddress": f"{peer.user}@{peer.host}:{peer.port}",
                                "location": str(peer.workspace_root),
                                "identityFile": str(peer.identity_file),
                                "knownHostsFile": str(peer.known_hosts_file),
                            },
                        })
                        response = await ws.receive_json(timeout=10)
                        assert response["kind"] == "response"
                        payload = response["payload"]
                        assert payload["ok"] is True
                        assert payload["workspace"]["exists"] is True
                        assert payload["git"] is True
                        assert payload["os"] in {"macos", "linux"}
            finally:
                server.stop()

        asyncio.run(run())


def test_prepare_remote_client_copies_config_over_fixture_sshd(tmp_path) -> None:
    try:
        env = SshTestEnvironment(tmp_path / "ssh-fixture")
    except SshTestEnvError as exc:
        pytest.skip(str(exc))

    with env as peer:
        payload = {
            "peerId": "fixture",
            "sshAddress": f"{peer.user}@{peer.host}:{peer.port}",
            "location": str(peer.workspace_root),
            "identityFile": str(peer.identity_file),
            "knownHostsFile": str(peer.known_hosts_file),
            "remoteConfigDir": str(peer.workspace_root / ".remote-griplab"),
            "remoteHubPort": 43141,
            "remoteClientPort": 3142,
        }
        diagnostics = diagnose_peer(payload)
        missing = [
            name
            for name in ("python", "uv", "git", "node")
            if not diagnostics.get(name, {}).get("ok", False)  # type: ignore[union-attr]
        ]
        if missing:
            pytest.skip(f"remote fixture missing required tools: {', '.join(missing)}")

        result = prepare_remote_client(payload, hub_port=3140)

        assert result["ok"] is True
        assert result["forward"]["remoteHubPort"] == 43141
        client = env.run_ssh(f"cat {shell_quote(peer.workspace_root / '.remote-griplab' / 'client.json')}")
        forward = env.run_ssh(f"cat {shell_quote(peer.workspace_root / '.remote-griplab' / 'forward.json')}")
        payload_file = env.run_ssh(f"cat {shell_quote(peer.workspace_root / '.remote-griplab' / 'client_payload.json')}")
        assert client.returncode == 0
        assert '"selfPeerId": "fixture"' in client.stdout
        assert '"url": "ws://127.0.0.1:43141/ws"' in client.stdout
        assert forward.returncode == 0
        assert '"remoteClientPort": 3142' in forward.stdout
        assert payload_file.returncode == 0
        assert "griplab-client-placeholder" in payload_file.stdout


def test_peer_bootstrap_starts_ephemeral_forwarded_process(tmp_path) -> None:
    try:
        env = SshTestEnvironment(tmp_path / "ssh-fixture")
    except SshTestEnvError as exc:
        pytest.skip(str(exc))

    with env as peer:
        async def run() -> None:
            service_root = tmp_path / "service"
            service_root.mkdir()
            remote_port = allocate_local_port()
            config = load_config(write_config(service_root, status_poll_interval_ms=1000))
            server = LocalClientServer(config)
            server.start()
            try:
                async with ClientSession() as session:
                    async with session.ws_connect(server.ws_url) as ws:
                        await ws.send_json({
                            "messageId": "m000001",
                            "kind": "request",
                            "method": "peer.bootstrap",
                            "payload": {
                                "peerId": "fixture",
                                "sshAddress": f"{peer.user}@{peer.host}:{peer.port}",
                                "location": str(peer.workspace_root),
                                "identityFile": str(peer.identity_file),
                                "knownHostsFile": str(peer.known_hosts_file),
                                "remotePort": remote_port,
                                "remoteCommand": f"python3 -m http.server {remote_port} --bind 127.0.0.1",
                            },
                        })
                        response = await ws.receive_json(timeout=10)
                        assert response["kind"] == "response"
                        payload = response["payload"]
                        assert payload["ok"] is True
                        assert payload["mode"] == "ephemeral"
                        body = await fetch_bootstrap_url(payload["localUrl"])
                        assert "Directory listing" in body

                        await ws.send_json({
                            "messageId": "m000002",
                            "kind": "request",
                            "method": "peer.bootstrap.stop",
                            "payload": {"bootstrapId": payload["bootstrapId"]},
                        })
                        stopped = await ws.receive_json(timeout=2)
                        assert stopped["payload"] == {"stopped": True}
            finally:
                server.stop()

        asyncio.run(run())


async def fetch_bootstrap_url(url: str) -> str:
    last_error: Exception | None = None
    for _ in range(40):
        try:
            return await asyncio.to_thread(lambda: urlopen(url, timeout=1).read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.1)
    raise AssertionError(f"bootstrap URL did not become reachable: {last_error}")

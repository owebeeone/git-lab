import json
import asyncio
from pathlib import Path
from urllib.request import urlopen

from aiohttp import ClientSession

from griplab_service.cli import main
from griplab_service.config import load_config
from griplab_service.local_client import LocalClientServer


def write_config(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess

    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "SSH Fixture"], check=True)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    (repo / ".grip-lab").mkdir()
    (repo / ".grip-lab" / "deps.json").write_text('{"name":"repo","kind":"pyproject","dependencies":[]}\n', encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
    config = {
        "selfPeerId": "me",
        "mode": "client",
        "listen": {"host": "127.0.0.1", "port": 0},
        "workspace": {"workspaceId": "local-main", "root": "repo"},
        "peers": [],
    }
    path = tmp_path / "client.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_load_config_resolves_workspace_relative_to_config(tmp_path: Path) -> None:
    path = write_config(tmp_path)

    config = load_config(path)

    assert config.self_peer_id == "me"
    assert config.listen.port == 0
    assert config.workspace.root == (tmp_path / "repo").resolve()


def test_local_client_health_and_probe(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path))
    server = LocalClientServer(config)
    server.start()
    try:
        with urlopen(f"{server.url}/health", timeout=2) as response:
            health = json.loads(response.read().decode("utf-8"))
        with urlopen(f"{server.url}/probe", timeout=2) as response:
            probe = json.loads(response.read().decode("utf-8"))
        with urlopen(f"{server.url}/workspace/status", timeout=2) as response:
            status = json.loads(response.read().decode("utf-8"))
        with urlopen(f"{server.url}/deps", timeout=2) as response:
            deps = json.loads(response.read().decode("utf-8"))
    finally:
        server.stop()

    assert health == {"ok": True, "mode": "client"}
    assert probe["ok"] is True
    assert probe["capabilities"]["os"]
    assert "git" in probe["capabilities"]
    assert "watchdog" in probe["capabilities"]
    assert status["repos"][0]["name"] == "repo"
    assert deps == {"repos": [""], "edges": [], "errors": {}}


def test_local_client_websocket_protocol(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "workspace.status.subscribe",
                        "streamId": "s000001",
                        "payload": {},
                    })
                    workspace_msg = await ws.receive_json(timeout=2)
                    assert workspace_msg["kind"] == "stream-event"
                    assert workspace_msg["streamId"] == "s000001"
                    assert workspace_msg["payload"]["event"] == "snapshot"
                    assert workspace_msg["payload"]["payload"]["repos"][0]["name"] == "repo"

                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "deps.get",
                        "payload": {},
                    })
                    deps_msg = await ws.receive_json(timeout=2)
                    assert deps_msg["kind"] == "response"
                    assert deps_msg["payload"] == {"repos": [""], "edges": [], "errors": {}}

                    await ws.send_json({
                        "messageId": "m000003",
                        "kind": "request",
                        "method": "missing.method",
                        "payload": {},
                    })
                    error_msg = await ws.receive_json(timeout=2)
                    assert error_msg["kind"] == "error"
                    assert error_msg["error"]["code"] == "unknown-method"
        finally:
            server.stop()

    asyncio.run(run())


def test_probe_cli_prints_probe_payload(tmp_path: Path, capsys) -> None:
    path = write_config(tmp_path)

    assert main(["probe", "--config", str(path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["selfPeerId"] == "me"

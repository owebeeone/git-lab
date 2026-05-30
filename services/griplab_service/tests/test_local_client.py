import json
from pathlib import Path
from urllib.request import urlopen

from griplab_service.cli import main
from griplab_service.config import load_config
from griplab_service.local_client import LocalClientServer


def write_config(tmp_path: Path) -> Path:
    config = {
        "selfPeerId": "me",
        "mode": "client",
        "listen": {"host": "127.0.0.1", "port": 0},
        "workspace": {"workspaceId": "local-main", "root": "."},
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
    assert config.workspace.root == tmp_path.resolve()


def test_local_client_health_and_probe(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path))
    server = LocalClientServer(config)
    server.start()
    try:
        with urlopen(f"{server.url}/health", timeout=2) as response:
            health = json.loads(response.read().decode("utf-8"))
        with urlopen(f"{server.url}/probe", timeout=2) as response:
            probe = json.loads(response.read().decode("utf-8"))
    finally:
        server.stop()

    assert health == {"ok": True, "mode": "client"}
    assert probe["ok"] is True
    assert probe["capabilities"]["os"]
    assert "git" in probe["capabilities"]
    assert "watchdog" in probe["capabilities"]


def test_probe_cli_prints_probe_payload(tmp_path: Path, capsys) -> None:
    path = write_config(tmp_path)

    assert main(["probe", "--config", str(path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["selfPeerId"] == "me"

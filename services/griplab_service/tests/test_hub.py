import asyncio
import json
from pathlib import Path

from aiohttp import ClientSession, WSCloseCode

from griplab_service.config import load_config
from griplab_service.hub import HubServer


def write_hub_config(tmp_path: Path) -> Path:
    config = {
        "selfPeerId": "hub",
        "mode": "hub",
        "listen": {"host": "127.0.0.1", "port": 0},
        "workspace": {
            "workspaceId": "hub-main",
            "root": ".",
        },
        "peers": [],
    }
    path = tmp_path / "hub.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_hub_peer_hello_and_presence_disconnect(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_hub_config(tmp_path))
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as watcher:
                    await watcher.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "peer.presence.subscribe",
                        "streamId": "presence0001",
                        "payload": {},
                    })
                    initial = await watcher.receive_json(timeout=2)
                    assert initial["payload"]["payload"] == {"peers": []}

                    client = await session.ws_connect(server.ws_url)
                    await client.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "peer.hello",
                        "payload": {
                            "peerId": "alice",
                            "name": "Alice",
                            "sshAddress": "alice@example.invalid",
                            "location": "~/work/project",
                            "os": "linux",
                            "shells": ["bash"],
                        },
                    })
                    hello = await client.receive_json(timeout=2)
                    assert hello["kind"] == "response"
                    assert hello["payload"] == {"peerId": "alice"}

                    online = await watcher.receive_json(timeout=2)
                    peers = online["payload"]["payload"]["peers"]
                    assert peers[0]["id"] == "alice"
                    assert peers[0]["online"] is True

                    await client.close(code=WSCloseCode.GOING_AWAY)
                    offline = await watcher.receive_json(timeout=2)
                    peers = offline["payload"]["payload"]["peers"]
                    assert peers[0]["id"] == "alice"
                    assert peers[0]["online"] is False
        finally:
            server.stop()

    asyncio.run(run())

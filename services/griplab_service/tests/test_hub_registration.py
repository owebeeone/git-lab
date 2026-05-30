import asyncio
import json
from pathlib import Path

from aiohttp import ClientSession

from griplab_service.config import load_config
from griplab_service.hub import HubServer
from griplab_service.hub_registration import HubRegistrationClient
from test_hub import write_hub_config
from test_local_client import write_config


def test_local_client_registers_with_hub_and_disconnects(tmp_path: Path) -> None:
    async def run() -> None:
        hub_root = tmp_path / "hub"
        hub_root.mkdir()
        hub_config = load_config(write_hub_config(hub_root))
        hub = HubServer(hub_config)
        hub.start()
        registration: HubRegistrationClient | None = None
        try:
            client_root = tmp_path / "client"
            client_root.mkdir()
            client_config_path = write_config(client_root)
            value = json.loads(client_config_path.read_text(encoding="utf-8"))
            value["hub"] = {"url": hub.ws_url, "heartbeatIntervalMs": 100}
            client_config_path.write_text(json.dumps(value), encoding="utf-8")
            client_config = load_config(client_config_path)
            registration = HubRegistrationClient(client_config)

            async with ClientSession() as session:
                async with session.ws_connect(hub.ws_url) as watcher:
                    await watcher.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "peer.presence.subscribe",
                        "streamId": "presence0001",
                        "payload": {},
                    })
                    await watcher.receive_json(timeout=2)
                    registration.start()

                    online = await receive_presence_with(watcher, "me", True)
                    assert online["status"] == "online"

                    registration.stop()
                    offline = await receive_presence_with(watcher, "me", False)
                    assert offline["status"] == "offline"
        finally:
            if registration is not None:
                registration.stop()
            hub.stop()

    asyncio.run(run())


async def receive_presence_with(ws, peer_id: str, online: bool) -> dict[str, object]:
    for _ in range(20):
        message = await ws.receive_json(timeout=2)
        peers = message["payload"]["payload"]["peers"]
        peer = next((item for item in peers if item["id"] == peer_id), None)
        if peer is not None and peer["online"] is online:
            return peer
    raise AssertionError(f"presence for {peer_id} did not reach online={online}")

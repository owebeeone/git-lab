import asyncio
import json
from pathlib import Path

from aiohttp import ClientSession

from griplab_service.config import load_config
from griplab_service.hub import HubServer
from griplab_service.hub_registration import HubRegistrationClient
from griplab_service.local_client import LocalClientServer
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


def test_hub_registration_proxies_routed_request_to_local_client(tmp_path: Path) -> None:
    async def run() -> None:
        hub_root = tmp_path / "hub"
        hub_root.mkdir()
        hub_config = load_config(write_hub_config(hub_root))
        hub = HubServer(hub_config)
        local: LocalClientServer | None = None
        registration: HubRegistrationClient | None = None
        hub.start()
        try:
            client_root = tmp_path / "client"
            client_root.mkdir()
            client_config_path = write_config(client_root)
            value = json.loads(client_config_path.read_text(encoding="utf-8"))
            value["hub"] = {"url": hub.ws_url, "heartbeatIntervalMs": 100}
            client_config_path.write_text(json.dumps(value), encoding="utf-8")
            client_config = load_config(client_config_path)
            local = LocalClientServer(client_config)
            local.start()
            registration = HubRegistrationClient(client_config, local_ws_url=local.ws_url)
            registration.start()

            async with ClientSession() as session:
                async with session.ws_connect(hub.ws_url) as caller:
                    await wait_for_presence(caller, "me")
                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "hub.route.request",
                        "payload": {
                            "targetPeerId": "me",
                            "method": "deps.get",
                            "payload": {},
                        },
                    })
                    response = await receive_message(caller, "m000001")
                    assert response["kind"] == "response"
                    assert response["messageId"] == "m000001"
                    assert response["method"] == "hub.route.request"
                    assert response["payload"] == {"repos": [""], "edges": [], "errors": {}}
        finally:
            if registration is not None:
                registration.stop()
            if local is not None:
                local.stop()
            hub.stop()

    asyncio.run(run())


def test_hub_registration_proxies_routed_subscription_to_local_client(tmp_path: Path) -> None:
    async def run() -> None:
        hub_root = tmp_path / "hub"
        hub_root.mkdir()
        hub_config = load_config(write_hub_config(hub_root))
        hub = HubServer(hub_config)
        local: LocalClientServer | None = None
        registration: HubRegistrationClient | None = None
        hub.start()
        try:
            client_root = tmp_path / "client"
            client_root.mkdir()
            client_config_path = write_config(client_root)
            value = json.loads(client_config_path.read_text(encoding="utf-8"))
            value["hub"] = {"url": hub.ws_url, "heartbeatIntervalMs": 100}
            client_config_path.write_text(json.dumps(value), encoding="utf-8")
            client_config = load_config(client_config_path)
            local = LocalClientServer(client_config)
            local.start()
            registration = HubRegistrationClient(client_config, local_ws_url=local.ws_url)
            registration.start()

            async with ClientSession() as session:
                async with session.ws_connect(hub.ws_url) as caller:
                    await wait_for_presence(caller, "me")
                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "hub.route.subscribe",
                        "streamId": "caller-tree",
                        "payload": {
                            "targetPeerId": "me",
                            "method": "tree.subscribe",
                            "payload": {},
                        },
                    })
                    event = await receive_stream_event(caller, "caller-tree")
                    assert event["kind"] == "stream-event"
                    assert event["method"] == "hub.route.subscribe"
                    assert event["streamId"] == "caller-tree"
                    assert event["payload"]["streamId"] == "caller-tree"
                    assert event["payload"]["event"] == "snapshot"
                    assert event["payload"]["payload"]["entries"]
                    registration.stop()
                    registration = None
        finally:
            if registration is not None:
                registration.stop()
            if local is not None:
                local.stop()
            hub.stop()

    asyncio.run(run())


def test_hub_registration_diff_subscribe_uses_registered_local_client(tmp_path: Path) -> None:
    async def run() -> None:
        hub_root = tmp_path / "hub"
        hub_root.mkdir()
        hub_config = load_config(write_hub_config(hub_root))
        hub = HubServer(hub_config)
        local: LocalClientServer | None = None
        registration: HubRegistrationClient | None = None
        hub.start()
        try:
            client_root = tmp_path / "client"
            client_root.mkdir()
            client_config_path = write_config(client_root)
            repo_root = client_root / "repo"
            (repo_root / "README.md").write_text("hello\nchanged\n", encoding="utf-8")
            value = json.loads(client_config_path.read_text(encoding="utf-8"))
            value["hub"] = {"url": hub.ws_url, "heartbeatIntervalMs": 100}
            client_config_path.write_text(json.dumps(value), encoding="utf-8")
            client_config = load_config(client_config_path)
            local = LocalClientServer(client_config)
            local.start()
            registration = HubRegistrationClient(client_config, local_ws_url=local.ws_url)
            registration.start()

            async with ClientSession() as session:
                async with session.ws_connect(hub.ws_url) as caller:
                    await wait_for_presence(caller, "me")
                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "diff.subscribe",
                        "streamId": "diff-stream",
                        "payload": {
                            "left": {
                                "peerId": "me",
                                "repoPath": "",
                                "path": "README.md",
                                "ref": {"kind": "head"},
                            },
                            "right": {
                                "peerId": "me",
                                "repoPath": "",
                                "path": "README.md",
                                "ref": {"kind": "working"},
                            },
                            "window": {"lineStart": 0, "lineEnd": 10},
                            "contextLines": 1,
                        },
                    })
                    event = await receive_stream_event(caller, "diff-stream")
                    payload = event["payload"]["payload"]
                    lines = [line for hunk in payload["hunks"] for line in hunk["lines"]]

                    assert event["method"] == "diff.subscribe"
                    assert payload["contentType"] == "application/vnd.griplab.diff+json;version=1"
                    assert any(line["kind"] == "add" and line["right"] == "changed" for line in lines)
        finally:
            if registration is not None:
                registration.stop()
            if local is not None:
                local.stop()
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


async def wait_for_presence(ws, peer_id: str) -> None:
    await ws.send_json({
        "messageId": "presence",
        "kind": "request",
        "method": "peer.presence.subscribe",
        "streamId": "presence-stream",
        "payload": {},
    })
    await receive_presence_with(ws, peer_id, True)


async def receive_message(ws, message_id: str) -> dict[str, object]:
    for _ in range(20):
        message = await ws.receive_json(timeout=2)
        if message.get("messageId") == message_id:
            return message
    raise AssertionError(f"message {message_id} was not received")


async def receive_stream_event(ws, stream_id: str) -> dict[str, object]:
    for _ in range(20):
        message = await ws.receive_json(timeout=2)
        if message.get("streamId") == stream_id:
            return message
    raise AssertionError(f"stream event {stream_id} was not received")

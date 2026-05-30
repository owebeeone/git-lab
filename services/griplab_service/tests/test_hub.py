import asyncio
import json
from pathlib import Path

from aiohttp import ClientSession, WSCloseCode
from filedelta import LineWindow, make_text_window_snapshot, text_window_snapshot_to_json

from griplab_service.config import load_config
from griplab_service.hub import HubServer
from griplab_service.hub.app import REGISTRY_KEY, PeerRegistry
from griplab_service.local_client import LocalClientServer
from test_local_client import write_config


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
                    peers = initial["payload"]["payload"]["peers"]
                    assert [peer["id"] for peer in peers] == []

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
                    alice = next(peer for peer in peers if peer["id"] == "alice")
                    assert alice["online"] is True
                    assert alice["status"] == "online"

                    await client.send_json({
                        "messageId": "m000003",
                        "kind": "request",
                        "method": "peer.heartbeat",
                        "payload": {"peerId": "alice", "ts": 1},
                    })
                    heartbeat = await client.receive_json(timeout=2)
                    assert heartbeat["kind"] == "response"
                    assert heartbeat["payload"] == {"ok": True}

                    await client.close(code=WSCloseCode.GOING_AWAY)
                    alice = await receive_presence_with(watcher, "alice", False)
                    assert alice["online"] is False
                    assert alice["status"] == "offline"
        finally:
            server.stop()

    asyncio.run(run())


def test_hub_presence_loads_configured_collaborators(tmp_path: Path) -> None:
    async def run() -> None:
        config_path = write_hub_config(tmp_path)
        (tmp_path / "collaborators.json").write_text(json.dumps([
            {
                "peerId": "weftpi",
                "name": "Weftpi",
                "sshAddress": "gianni@example.invalid",
                "location": "~/gitlab/grip-dev",
            }
        ]), encoding="utf-8")
        config = load_config(config_path)
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "peer.presence.subscribe",
                        "streamId": "presence0001",
                        "payload": {},
                    })
                    snapshot = await ws.receive_json(timeout=2)
                    peers = snapshot["payload"]["payload"]["peers"]
                    assert [peer["id"] for peer in peers] == ["weftpi"]
                    configured = peers[0]
                    assert configured["status"] in {"starting", "error"}
                    assert configured["online"] is False
                    assert configured["sshAddress"] == "gianni@example.invalid"
        finally:
            server.stop()

    asyncio.run(run())


def test_hub_peer_health_and_collaborator_mutation(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_hub_config(tmp_path))
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "peer.collaborator.upsert",
                        "payload": {
                            "peerId": "alice",
                            "name": "Alice",
                            "sshAddress": "alice@example.invalid",
                            "location": "~/work/project",
                        },
                    })
                    upserted = await ws.receive_json(timeout=2)
                    assert upserted["kind"] == "response"
                    assert upserted["payload"]["collaborator"]["peerId"] == "alice"

                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "peer.health.get",
                        "payload": {"peerId": "alice"},
                    })
                    health = await ws.receive_json(timeout=2)
                    assert health["payload"]["health"]["peerId"] == "alice"
                    assert health["payload"]["health"]["status"] in {"starting", "error"}
                    assert any(check["id"] == "log" for check in health["payload"]["health"]["checks"])

                    await ws.send_json({
                        "messageId": "m000003",
                        "kind": "request",
                        "method": "peer.collaborator.remove",
                        "payload": {"peerId": "alice"},
                    })
                    removed = await ws.receive_json(timeout=2)
                    assert removed["payload"] == {"removed": True}
        finally:
            server.stop()

    asyncio.run(run())


def test_hub_assigns_distinct_remote_hub_ports_per_collaborator(tmp_path: Path) -> None:
    config = load_config(write_hub_config(tmp_path))
    registry = PeerRegistry(config)

    assert registry._remote_hub_port_for("weftpi") == 43140
    assert registry._remote_hub_port_for("weftpi-another") == 43141
    assert registry._remote_hub_port_for("weftpi") == 43140
    assert registry._remote_client_port_for("weftpi") == 3141
    assert registry._remote_client_port_for("weftpi-another") == 3142
    assert registry._remote_client_port_for("weftpi") == 3141


def test_hub_chat_post_subscribe_and_persist_order(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_hub_config(tmp_path))
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "peer.hello",
                        "payload": {"peerId": "alice", "name": "Alice"},
                    })
                    assert (await ws.receive_json(timeout=2))["payload"] == {"peerId": "alice"}

                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "chat.subscribe",
                        "streamId": "chat0001",
                        "payload": {},
                    })
                    initial = await ws.receive_json(timeout=2)
                    assert initial["payload"]["payload"] == {"messages": []}

                    await ws.send_json({
                        "messageId": "m000003",
                        "kind": "request",
                        "method": "chat.post",
                        "payload": {
                            "text": "hello",
                            "links": [{"kind": "repo", "label": "root", "target": "repo::"}],
                        },
                    })
                    posted = await ws.receive_json(timeout=2)
                    assert posted["kind"] == "response"
                    message = posted["payload"]["message"]
                    assert message["senderId"] == "alice"
                    assert message["text"] == "hello"

                    update = await ws.receive_json(timeout=2)
                    messages = update["payload"]["payload"]["messages"]
                    assert [item["id"] for item in messages] == [message["id"]]
                    assert messages[0]["links"][0]["kind"] == "repo"

                    files = sorted((tmp_path / ".grip-lab" / "chat").glob("*.json"))
                    assert [path.stem for path in files] == [message["id"]]
        finally:
            server.stop()

    asyncio.run(run())


def test_hub_chat_rejects_malformed_links(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_hub_config(tmp_path))
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "chat.post",
                        "payload": {
                            "text": "bad link",
                            "links": [{"kind": "bad", "label": "bad", "target": "x"}],
                        },
                    })
                    rejected = await ws.receive_json(timeout=2)
                    assert rejected["kind"] == "error"
                    assert rejected["error"]["code"] == "bad-chat-message"
        finally:
            server.stop()

    asyncio.run(run())


def test_hub_routes_request_to_target_peer(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_hub_config(tmp_path))
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as caller:
                    target = await session.ws_connect(server.ws_url)
                    await hello_peer(target, "target")

                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "hub.route.request",
                        "payload": {
                            "targetPeerId": "target",
                            "method": "echo.ping",
                            "payload": {"value": 42},
                        },
                    })
                    routed = await target.receive_json(timeout=2)
                    assert routed["kind"] == "request"
                    assert routed["method"] == "echo.ping"
                    assert routed["payload"] == {"value": 42}
                    assert routed["messageId"] != "m000001"

                    await target.send_json({
                        "messageId": routed["messageId"],
                        "kind": "response",
                        "method": "echo.ping",
                        "payload": {"ok": True, "value": 42},
                    })
                    response = await caller.receive_json(timeout=2)
                    assert response["kind"] == "response"
                    assert response["messageId"] == "m000001"
                    assert response["method"] == "hub.route.request"
                    assert response["payload"] == {"ok": True, "value": 42}

                    await target.close()
        finally:
            server.stop()

    asyncio.run(run())


def test_hub_routes_request_through_registered_tunnel(tmp_path: Path) -> None:
    async def run() -> None:
        hub_root = tmp_path / "hub"
        hub_root.mkdir()
        local_root = tmp_path / "local-peer"
        local_root.mkdir()
        hub_config = load_config(write_hub_config(hub_root))
        local_config_path = write_config(local_root)
        local_value = json.loads(local_config_path.read_text(encoding="utf-8"))
        local_value["selfPeerId"] = "target"
        local_config_path.write_text(json.dumps(local_value), encoding="utf-8")
        local_config = load_config(local_config_path)
        hub = HubServer(hub_config)
        local = LocalClientServer(local_config)
        hub.start()
        local.start()
        try:
            assert hub._runner is not None
            registry = hub._runner.app[REGISTRY_KEY]  # type: ignore[union-attr]
            registry.register_tunnel("target", local_peer_port=int(local.url.rsplit(":", 1)[1]))
            async with ClientSession() as session:
                async with session.ws_connect(hub.ws_url) as caller:
                    target = await session.ws_connect(hub.ws_url)
                    await hello_peer(target, "target")

                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "hub.route.request",
                        "payload": {
                            "targetPeerId": "target",
                            "method": "deps.get",
                            "payload": {},
                        },
                    })
                    response = await caller.receive_json(timeout=2)
                    assert response["kind"] == "response"
                    assert response["payload"] == {"repos": [""], "edges": [], "errors": {}}
                    await target.close()
        finally:
            local.stop()
            hub.stop()

    asyncio.run(run())


def test_hub_routes_subscription_through_registered_tunnel(tmp_path: Path) -> None:
    async def run() -> None:
        hub_root = tmp_path / "hub"
        hub_root.mkdir()
        local_root = tmp_path / "local-peer"
        local_root.mkdir()
        hub_config = load_config(write_hub_config(hub_root))
        local_config_path = write_config(local_root)
        local_value = json.loads(local_config_path.read_text(encoding="utf-8"))
        local_value["selfPeerId"] = "target"
        local_config_path.write_text(json.dumps(local_value), encoding="utf-8")
        local_config = load_config(local_config_path)
        hub = HubServer(hub_config)
        local = LocalClientServer(local_config)
        hub.start()
        local.start()
        try:
            assert hub._runner is not None
            registry = hub._runner.app[REGISTRY_KEY]  # type: ignore[union-attr]
            registry.register_tunnel("target", local_peer_port=int(local.url.rsplit(":", 1)[1]))
            async with ClientSession() as session:
                async with session.ws_connect(hub.ws_url) as caller:
                    target = await session.ws_connect(hub.ws_url)
                    await hello_peer(target, "target")

                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "hub.route.subscribe",
                        "streamId": "caller-tree",
                        "payload": {
                            "targetPeerId": "target",
                            "method": "tree.subscribe",
                            "payload": {},
                        },
                    })
                    event = await caller.receive_json(timeout=2)
                    assert event["kind"] == "stream-event"
                    assert event["method"] == "hub.route.subscribe"
                    assert event["streamId"] == "caller-tree"
                    assert event["payload"]["streamId"] == "caller-tree"
                    assert event["payload"]["event"] == "snapshot"
                    assert event["payload"]["payload"]["entries"]
                    await target.close()
        finally:
            local.stop()
            hub.stop()

    asyncio.run(run())


def test_hub_routes_subscription_events_to_caller_stream(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_hub_config(tmp_path))
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as caller:
                    target = await session.ws_connect(server.ws_url)
                    await hello_peer(target, "target")

                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "hub.route.subscribe",
                        "streamId": "caller-stream",
                        "payload": {
                            "targetPeerId": "target",
                            "method": "echo.subscribe",
                            "payload": {"topic": "demo"},
                        },
                    })
                    routed = await target.receive_json(timeout=2)
                    assert routed["kind"] == "request"
                    assert routed["method"] == "echo.subscribe"
                    assert routed["streamId"] != "caller-stream"
                    assert routed["payload"] == {"topic": "demo"}

                    await target.send_json({
                        "messageId": routed["messageId"],
                        "kind": "stream-event",
                        "method": "echo.subscribe",
                        "streamId": routed["streamId"],
                        "payload": {
                            "streamId": routed["streamId"],
                            "seq": 1,
                            "event": "snapshot",
                            "payload": {"items": [1, 2, 3]},
                        },
                    })
                    event = await caller.receive_json(timeout=2)
                    assert event["kind"] == "stream-event"
                    assert event["method"] == "hub.route.subscribe"
                    assert event["streamId"] == "caller-stream"
                    assert event["payload"] == {
                        "streamId": "caller-stream",
                        "seq": 1,
                        "event": "snapshot",
                        "payload": {"items": [1, 2, 3]},
                    }

                    await target.close()
        finally:
            server.stop()

    asyncio.run(run())


def test_hub_route_errors_when_target_unknown(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_hub_config(tmp_path))
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as caller:
                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "hub.route.request",
                        "payload": {
                            "targetPeerId": "missing",
                            "method": "echo.ping",
                            "payload": {},
                        },
                    })
                    response = await caller.receive_json(timeout=2)
                    assert response["kind"] == "error"
                    assert response["messageId"] == "m000001"
                    assert response["error"]["code"] == "peer-offline"
        finally:
            server.stop()

    asyncio.run(run())


def test_hub_routed_stream_errors_when_target_disconnects(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_hub_config(tmp_path))
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as caller:
                    target = await session.ws_connect(server.ws_url)
                    await hello_peer(target, "target")

                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "hub.route.subscribe",
                        "streamId": "caller-stream",
                        "payload": {
                            "targetPeerId": "target",
                            "method": "echo.subscribe",
                            "payload": {},
                        },
                    })
                    await target.receive_json(timeout=2)
                    await target.close()

                    event = await caller.receive_json(timeout=2)
                    assert event["kind"] == "stream-event"
                    assert event["streamId"] == "caller-stream"
                    assert event["payload"]["event"] == "error"
                    assert event["payload"]["payload"]["code"] == "peer-offline"
        finally:
            server.stop()

    asyncio.run(run())


def test_hub_routed_request_times_out(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(PeerRegistry, "route_request_timeout_seconds", 0.01)

    async def run() -> None:
        config = load_config(write_hub_config(tmp_path))
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as caller:
                    target = await session.ws_connect(server.ws_url)
                    await hello_peer(target, "target")

                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "hub.route.request",
                        "payload": {
                            "targetPeerId": "target",
                            "method": "echo.never",
                            "payload": {},
                        },
                    })
                    await target.receive_json(timeout=2)
                    response = await caller.receive_json(timeout=2)
                    assert response["kind"] == "error"
                    assert response["messageId"] == "m000001"
                    assert response["error"]["code"] == "target-timeout"
                    await target.close()
        finally:
            server.stop()

    asyncio.run(run())


def test_hub_diff_subscribe_routes_file_streams_and_publishes_diff(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_hub_config(tmp_path))
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as caller:
                    left = await session.ws_connect(server.ws_url)
                    right = await session.ws_connect(server.ws_url)
                    await hello_peer(left, "left")
                    await hello_peer(right, "right")

                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "diff.subscribe",
                        "streamId": "diff-stream",
                        "payload": {
                            "left": {
                                "peerId": "left",
                                "repoPath": "",
                                "path": "src/app.ts",
                                "ref": {"kind": "working"},
                            },
                            "right": {
                                "peerId": "right",
                                "repoPath": "",
                                "path": "src/app.ts",
                                "ref": {"kind": "working"},
                            },
                            "window": {"lineStart": 0, "lineEnd": 5},
                            "contextLines": 1,
                        },
                    })
                    left_request = await left.receive_json(timeout=2)
                    right_request = await right.receive_json(timeout=2)
                    assert left_request["method"] == "file.subscribe"
                    assert right_request["method"] == "file.subscribe"
                    assert left_request["payload"]["window"] == {"lineStart": 0, "lineEnd": 6}
                    assert right_request["payload"]["window"] == {"lineStart": 0, "lineEnd": 6}

                    await send_file_snapshot(left, left_request, "left", b"a\nold\nc\n", "fv000001")
                    await send_file_snapshot(right, right_request, "right", b"a\nnew\nc\n", "fv000002")

                    event = await caller.receive_json(timeout=2)
                    payload = event["payload"]["payload"]
                    assert event["kind"] == "stream-event"
                    assert event["method"] == "diff.subscribe"
                    assert event["streamId"] == "diff-stream"
                    assert payload["contentType"] == "application/vnd.griplab.diff+json;version=1"
                    assert payload["left"]["peerId"] == "left"
                    assert payload["right"]["peerId"] == "right"
                    assert payload["hunks"][0]["lines"][1]["kind"] == "change"

                    await caller.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "diff.unsubscribe",
                        "payload": {"streamId": "diff-stream"},
                    })
                    response = await caller.receive_json(timeout=2)
                    assert response["payload"] == {"stopped": True}
                    assert (await left.receive_json(timeout=2))["method"] == "file.unsubscribe"
                    assert (await right.receive_json(timeout=2))["method"] == "file.unsubscribe"
                    await left.close()
                    await right.close()
        finally:
            server.stop()

    asyncio.run(run())


def test_hub_diff_source_error_publishes_diagnostic(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_hub_config(tmp_path))
        server = HubServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as caller:
                    left = await session.ws_connect(server.ws_url)
                    await hello_peer(left, "left")

                    await caller.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "diff.subscribe",
                        "streamId": "diff-stream",
                        "payload": {
                            "left": {
                                "peerId": "left",
                                "repoPath": "",
                                "path": "src/app.ts",
                                "ref": {"kind": "working"},
                            },
                            "right": {
                                "peerId": "missing",
                                "repoPath": "",
                                "path": "src/app.ts",
                                "ref": {"kind": "working"},
                            },
                            "window": {"lineStart": 0, "lineEnd": 5},
                            "contextLines": 1,
                        },
                    })

                    event = await caller.receive_json(timeout=2)
                    payload = event["payload"]["payload"]
                    assert payload["diagnostics"][0]["code"] == "peer-offline"
                    assert payload["diagnostics"][0]["endpoint"] == "right"

                    await left.close()
        finally:
            server.stop()

    asyncio.run(run())


async def hello_peer(ws: object, peer_id: str) -> None:
    await ws.send_json({
        "messageId": f"hello-{peer_id}",
        "kind": "request",
        "method": "peer.hello",
        "payload": {"peerId": peer_id, "name": peer_id.title()},
    })
    response = await ws.receive_json(timeout=2)
    assert response["kind"] == "response"
    assert response["payload"] == {"peerId": peer_id}


async def receive_presence_with(ws: object, peer_id: str, online: bool) -> dict[str, object]:
    for _ in range(20):
        message = await ws.receive_json(timeout=2)
        peers = message["payload"]["payload"]["peers"]
        peer = next((item for item in peers if item["id"] == peer_id), None)
        if peer is not None and peer["online"] is online:
            return peer
    raise AssertionError(f"presence for {peer_id} did not reach online={online}")


async def send_file_snapshot(ws: object, routed_request: dict, resource_id: str, data: bytes, file_version: str) -> None:
    snapshot = make_text_window_snapshot(
        resource_id=resource_id,
        window_id=f"{resource_id}:window",
        data=data,
        window=LineWindow(0, 20),
        file_version=file_version,
        window_version="wv000001",
    )
    await ws.send_json({
        "messageId": routed_request["messageId"],
        "kind": "stream-event",
        "method": "file.subscribe",
        "streamId": routed_request["streamId"],
        "payload": {
            "streamId": routed_request["streamId"],
            "seq": 1,
            "event": "snapshot",
            "payload": text_window_snapshot_to_json(snapshot),
        },
    })

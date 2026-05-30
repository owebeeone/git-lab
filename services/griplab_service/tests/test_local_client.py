import json
import asyncio
from pathlib import Path
from urllib.request import urlopen
import subprocess

from aiohttp import ClientSession, WSCloseCode

from griplab_service.cli import main
from griplab_service.config import load_config
from griplab_service.local_client import LocalClientServer
from griplab_service.local_client.tree import tree_snapshot_payload


def write_config(tmp_path: Path, *, status_poll_interval_ms: int = 1000) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

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
        "workspace": {
            "workspaceId": "local-main",
            "root": "repo",
            "statusPollIntervalMs": status_poll_interval_ms,
        },
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


def test_local_client_chat_post_and_subscribe(tmp_path: Path) -> None:
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
                        "method": "chat.subscribe",
                        "streamId": "chat0001",
                        "payload": {},
                    })
                    initial = await ws.receive_json(timeout=2)
                    assert initial["payload"]["payload"] == {"messages": []}

                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "chat.post",
                        "payload": {"text": "local hello", "links": []},
                    })
                    posted = await ws.receive_json(timeout=2)
                    assert posted["kind"] == "response"
                    assert posted["payload"]["message"]["senderId"] == "me"

                    update = await ws.receive_json(timeout=2)
                    messages = update["payload"]["payload"]["messages"]
                    assert [message["text"] for message in messages] == ["local hello"]
        finally:
            server.stop()

    asyncio.run(run())


def test_tree_snapshot_excludes_ignored_paths(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path))
    (config.workspace.root / "src").mkdir()
    (config.workspace.root / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (config.workspace.root / "node_modules").mkdir()
    (config.workspace.root / "node_modules" / "ignored.js").write_text("nope\n", encoding="utf-8")

    payload = tree_snapshot_payload(config.workspace.root)
    paths = {entry["path"] for entry in payload["entries"]}

    assert "README.md" in paths
    assert "src/app.py" in paths
    assert "node_modules/ignored.js" not in paths
    assert payload["version"]


def test_tree_stream_publishes_watchdog_changes_and_refresh(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=1000))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "tree.subscribe",
                        "streamId": "tree0001",
                        "payload": {},
                    })
                    first = await ws.receive_json(timeout=2)
                    assert first["kind"] == "stream-event"
                    assert first["streamId"] == "tree0001"
                    assert first["payload"]["seq"] == 1
                    entries = first["payload"]["payload"]["entries"]
                    assert any(entry["path"] == "README.md" for entry in entries)

                    (config.workspace.root / "src").mkdir()
                    (config.workspace.root / "src" / "new.py").write_text("print('hi')\n", encoding="utf-8")
                    changed = await ws.receive_json(timeout=2)
                    assert changed["payload"]["seq"] == 2
                    changed_paths = {entry["path"] for entry in changed["payload"]["payload"]["entries"]}
                    assert "src/new.py" in changed_paths

                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "tree.refresh",
                        "payload": {},
                    })
                    snapshot = await ws.receive_json(timeout=2)
                    response = await ws.receive_json(timeout=2)
                    assert snapshot["kind"] == "stream-event"
                    assert snapshot["payload"]["seq"] == 3
                    assert response["kind"] == "response"
                    assert response["payload"] == {"refreshed": 1}
        finally:
            server.stop()

    asyncio.run(run())


def test_tree_stream_ignores_ignored_path_changes(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=1000))
        (config.workspace.root / "node_modules").mkdir()
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "tree.subscribe",
                        "streamId": "tree0001",
                        "payload": {},
                    })
                    await ws.receive_json(timeout=2)

                    (config.workspace.root / "node_modules" / "ignored.js").write_text("nope\n", encoding="utf-8")
                    try:
                        await ws.receive_json(timeout=0.5)
                    except TimeoutError:
                        pass
                    else:
                        raise AssertionError("ignored path emitted a tree snapshot")
        finally:
            server.stop()

    asyncio.run(run())


def test_file_stream_sends_snapshot_and_delta_on_local_edit(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=1000))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "file.subscribe",
                        "streamId": "file0001",
                        "payload": {
                            "repoPath": "",
                            "path": "README.md",
                            "ref": "working",
                            "window": {"lineStart": 0, "lineEnd": 10},
                        },
                    })
                    first = await ws.receive_json(timeout=2)
                    assert first["kind"] == "stream-event"
                    assert first["method"] == "file.subscribe"
                    assert first["payload"]["event"] == "snapshot"
                    snapshot = first["payload"]["payload"]
                    assert snapshot["scope"] == "text-window"
                    assert snapshot["lineStart"] == 0
                    assert snapshot["lineEnd"] == 1

                    (config.workspace.root / "README.md").write_text("hello\nchanged\n", encoding="utf-8")
                    changed = await ws.receive_json(timeout=2)
                    assert changed["payload"]["event"] in {"delta", "reset"}
                    if changed["payload"]["event"] == "delta":
                        assert changed["payload"]["payload"]["resultHash"]
                    else:
                        assert changed["payload"]["payload"]["snapshot"]["contentHash"]
        finally:
            server.stop()

    asyncio.run(run())


def test_file_window_update_routes_to_subscription(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=1000))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "file.subscribe",
                        "streamId": "file0001",
                        "payload": {
                            "repoPath": "",
                            "path": "README.md",
                            "ref": "working",
                            "window": {"lineStart": 0, "lineEnd": 1},
                        },
                    })
                    await ws.receive_json(timeout=2)

                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "file.window.update",
                        "payload": {
                            "streamId": "file0001",
                            "window": {"lineStart": 0, "lineEnd": 2},
                        },
                    })
                    update = await ws.receive_json(timeout=2)
                    response = await ws.receive_json(timeout=2)
                    assert update["payload"]["event"] in {"delta", "reset"}
                    assert response["kind"] == "response"
                    assert response["payload"] == {"updated": True}
        finally:
            server.stop()

    asyncio.run(run())


def test_file_stream_reports_unsupported_ref(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=1000))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "file.subscribe",
                        "streamId": "file0001",
                        "payload": {
                            "repoPath": "",
                            "path": "README.md",
                            "ref": "head",
                            "window": {"lineStart": 0, "lineEnd": 10},
                        },
                    })
                    error = await ws.receive_json(timeout=2)
                    assert error["kind"] == "stream-event"
                    assert error["payload"]["event"] == "error"
                    assert error["payload"]["payload"]["code"] == "unsupported-ref"
        finally:
            server.stop()

    asyncio.run(run())


def test_command_run_updates_sessions_and_output_streams(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=1000))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "sessions.subscribe",
                        "streamId": "sessions0001",
                        "payload": {},
                    })
                    initial = await ws.receive_json(timeout=2)
                    assert initial["payload"]["payload"] == {"sessions": []}

                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "cmd.run",
                        "payload": {
                            "argv": ["python", "-c", "print('session-ok')"],
                            "repos": [""],
                            "peerId": "me",
                        },
                    })
                    response = await ws.receive_json(timeout=2)
                    assert response["kind"] == "response"
                    session_id = response["payload"]["sessionId"]

                    created = await ws.receive_json(timeout=2)
                    sessions = created["payload"]["payload"]["sessions"]
                    assert sessions[0]["id"] == session_id
                    assert sessions[0]["targets"][0]["exitCode"] is None

                    await ws.send_json({
                        "messageId": "m000003",
                        "kind": "request",
                        "method": "session.output.subscribe",
                        "streamId": "output0001",
                        "payload": {"sessionId": session_id, "repoPath": ""},
                    })
                    output = await ws.receive_json(timeout=2)
                    assert output["payload"]["payload"]["sessionId"] == session_id

                    final_output = output
                    for _ in range(5):
                        msg = await ws.receive_json(timeout=2)
                        if msg["method"] == "session.output.subscribe":
                            final_output = msg
                            if "session-ok" in msg["payload"]["payload"]["output"]:
                                break
                    assert "session-ok" in final_output["payload"]["payload"]["output"]

                    for _ in range(5):
                        msg = await ws.receive_json(timeout=2)
                        if msg["method"] == "sessions.subscribe":
                            target = msg["payload"]["payload"]["sessions"][0]["targets"][0]
                            if target["exitCode"] is not None:
                                assert target["exitCode"] == 0
                                break
                    else:
                        raise AssertionError("command session did not finish")
        finally:
            server.stop()

    asyncio.run(run())


def test_command_sessions_reconstruct_after_restart(tmp_path: Path) -> None:
    async def run_command_once() -> str:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=1000))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "sessions.subscribe",
                        "streamId": "sessions0001",
                        "payload": {},
                    })
                    await ws.receive_json(timeout=2)

                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "cmd.run",
                        "payload": {
                            "argv": ["python", "-c", "print('persisted-session')"],
                            "repos": [""],
                            "peerId": "me",
                        },
                    })
                    response = await ws.receive_json(timeout=2)
                    session_id = response["payload"]["sessionId"]
                    for _ in range(8):
                        msg = await ws.receive_json(timeout=2)
                        if msg["method"] != "sessions.subscribe":
                            continue
                        target = msg["payload"]["payload"]["sessions"][0]["targets"][0]
                        if target["exitCode"] is not None:
                            assert target["exitCode"] == 0
                            return session_id
                    raise AssertionError("session did not finish")
        finally:
            server.stop()

    async def verify_restart(session_id: str) -> None:
        config = load_config(tmp_path / "client.json")
        session_dir = config.workspace.root / ".grip-lab" / "sessions" / session_id
        assert (session_dir / "metadata.json").is_file()
        assert "persisted-session" in (session_dir / "t000001" / "output.log").read_text(encoding="utf-8")
        assert (session_dir / "events.jsonl").is_file()

        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "sessions.subscribe",
                        "streamId": "sessions0001",
                        "payload": {},
                    })
                    snapshot = await ws.receive_json(timeout=2)
                    restored = snapshot["payload"]["payload"]["sessions"][0]
                    assert restored["id"] == session_id
                    assert restored["targets"][0]["exitCode"] == 0

                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "session.output.subscribe",
                        "streamId": "output0001",
                        "payload": {"sessionId": session_id, "repoPath": ""},
                    })
                    output = await ws.receive_json(timeout=2)
                    assert "persisted-session" in output["payload"]["payload"]["output"]
        finally:
            server.stop()

    restored_session_id = asyncio.run(run_command_once())
    asyncio.run(verify_restart(restored_session_id))


def test_sessions_query_filters_by_text_status_peer_and_repo(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=1000))
        (config.workspace.root / "subrepo").mkdir()
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "cmd.run",
                        "payload": {
                            "argv": ["python", "-c", "print('query-target')"],
                            "repos": [""],
                            "peerId": "me",
                        },
                    })
                    ok_response = await ws.receive_json(timeout=2)
                    ok_session_id = ok_response["payload"]["sessionId"]

                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "cmd.run",
                        "payload": {
                            "argv": ["python", "-c", "import sys; print('query-fail'); sys.exit(3)"],
                            "repos": ["subrepo"],
                            "peerId": "me",
                        },
                    })
                    fail_response = await ws.receive_json(timeout=2)
                    fail_session_id = fail_response["payload"]["sessionId"]

                    await wait_for_query_session(ws, ok_session_id)
                    await wait_for_query_session(ws, fail_session_id)

                    await ws.send_json({
                        "messageId": "m000003",
                        "kind": "request",
                        "method": "sessions.query",
                        "payload": {"text": "query-target", "status": ["ok"], "peers": ["me"], "limit": 10},
                    })
                    text_query = await ws.receive_json(timeout=2)
                    matches = text_query["payload"]["matches"]
                    assert [item["session"]["id"] for item in matches] == [ok_session_id]

                    await ws.send_json({
                        "messageId": "m000004",
                        "kind": "request",
                        "method": "sessions.query",
                        "payload": {"status": ["error"], "repos": ["subrepo"], "limit": 10},
                    })
                    error_query = await ws.receive_json(timeout=2)
                    matches = error_query["payload"]["matches"]
                    assert [item["session"]["id"] for item in matches] == [fail_session_id]
                    assert matches[0]["status"] == "error"
        finally:
            server.stop()

    asyncio.run(run())


async def wait_for_query_session(ws, session_id: str) -> None:
    for index in range(20):
        await ws.send_json({
            "messageId": f"q{index:06d}",
            "kind": "request",
            "method": "sessions.query",
            "payload": {"limit": 100},
        })
        response = await ws.receive_json(timeout=2)
        for item in response["payload"]["matches"]:
            if item["session"]["id"] == session_id and item["status"] != "running":
                return
        await asyncio.sleep(0.05)
    raise AssertionError(f"session did not finish: {session_id}")


def test_terminal_open_input_resize_close_streams_output(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=1000))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "term.open",
                        "payload": {"argv": ["cat"], "repoPath": "", "rows": 24, "cols": 80, "peerId": "me"},
                    })
                    opened = await ws.receive_json(timeout=2)
                    assert opened["kind"] == "response"
                    session_id = opened["payload"]["sessionId"]

                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "session.output.subscribe",
                        "streamId": "output0001",
                        "payload": {"sessionId": session_id, "repoPath": ""},
                    })
                    await ws.receive_json(timeout=2)

                    await ws.send_json({
                        "messageId": "m000003",
                        "kind": "request",
                        "method": "term.input",
                        "payload": {"sessionId": session_id, "data": "pty-ok\n"},
                    })
                    input_response = await ws.receive_json(timeout=2)
                    assert input_response["payload"] == {"written": True}

                    seen = ""
                    for _ in range(8):
                        msg = await ws.receive_json(timeout=2)
                        if msg["method"] == "session.output.subscribe":
                            seen = msg["payload"]["payload"]["output"]
                            if "pty-ok" in seen:
                                break
                    assert "pty-ok" in seen

                    await ws.send_json({
                        "messageId": "m000004",
                        "kind": "request",
                        "method": "term.resize",
                        "payload": {"sessionId": session_id, "rows": 40, "cols": 100},
                    })
                    resize_response = await receive_response(ws, "m000004")
                    assert resize_response["payload"] == {"resized": True}

                    await ws.send_json({
                        "messageId": "m000005",
                        "kind": "request",
                        "method": "term.close",
                        "payload": {"sessionId": session_id},
                    })
                    close_response = await receive_response(ws, "m000005")
                    assert close_response["payload"] == {"closed": True}

                    session_dir = config.workspace.root / ".grip-lab" / "sessions" / session_id
                    assert "pty-ok" in (session_dir / "t000001" / "output.log").read_text(encoding="utf-8")
        finally:
            server.stop()

    asyncio.run(run())


async def receive_response(ws, message_id: str) -> dict:
    for _ in range(10):
        msg = await ws.receive_json(timeout=2)
        if msg.get("kind") == "response" and msg.get("messageId") == message_id:
            return msg
    raise AssertionError(f"response not received: {message_id}")


def test_workspace_status_stream_polls_changes_and_suppresses_duplicates(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=100))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await subscribe_workspace(ws)
                    first = await ws.receive_json(timeout=2)
                    assert first["payload"]["seq"] == 1
                    assert first["payload"]["payload"]["repos"][0]["dirty"] is False

                    try:
                        await ws.receive_json(timeout=0.25)
                    except TimeoutError:
                        pass
                    else:
                        raise AssertionError("unchanged poll emitted a duplicate snapshot")

                    (config.workspace.root / "README.md").write_text("changed\n", encoding="utf-8")
                    changed = await ws.receive_json(timeout=2)
                    assert changed["payload"]["seq"] == 2
                    repo = changed["payload"]["payload"]["repos"][0]
                    assert repo["dirty"] is True
                    assert repo["changedFiles"] == [{"path": "README.md", "change": "modified"}]

                    (config.workspace.root / "new.txt").write_text("new\n", encoding="utf-8")
                    untracked = await ws.receive_json(timeout=2)
                    assert untracked["payload"]["seq"] == 3
                    paths = {item["path"] for item in untracked["payload"]["payload"]["repos"][0]["changedFiles"]}
                    assert paths == {"README.md", "new.txt"}
        finally:
            server.stop()

    asyncio.run(run())


def test_workspace_status_refresh_forces_snapshot(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=1000))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await subscribe_workspace(ws)
                    await ws.receive_json(timeout=2)
                    await ws.send_json({
                        "messageId": "m000002",
                        "kind": "request",
                        "method": "workspace.status.refresh",
                        "payload": {},
                    })
                    snapshot = await ws.receive_json(timeout=2)
                    response = await ws.receive_json(timeout=2)
                    assert snapshot["kind"] == "stream-event"
                    assert snapshot["payload"]["seq"] == 2
                    assert response["kind"] == "response"
                    assert response["payload"] == {"refreshed": 1}
        finally:
            server.stop()

    asyncio.run(run())


def test_workspace_status_refresh_without_subscriber_is_noop(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=100))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                async with session.ws_connect(server.ws_url) as ws:
                    await ws.send_json({
                        "messageId": "m000001",
                        "kind": "request",
                        "method": "workspace.status.refresh",
                        "payload": {},
                    })
                    response = await ws.receive_json(timeout=2)
                    assert response["kind"] == "response"
                    assert response["payload"] == {"refreshed": 0}
        finally:
            server.stop()

    asyncio.run(run())


def test_workspace_status_polling_stops_after_disconnect(tmp_path: Path) -> None:
    async def run() -> None:
        config = load_config(write_config(tmp_path, status_poll_interval_ms=100))
        server = LocalClientServer(config)
        server.start()
        try:
            async with ClientSession() as session:
                ws = await session.ws_connect(server.ws_url)
                await subscribe_workspace(ws)
                await ws.receive_json(timeout=2)
                await ws.close(code=WSCloseCode.GOING_AWAY)
                await asyncio.sleep(0.25)
                assert ws.closed
        finally:
            server.stop()

    asyncio.run(run())


async def subscribe_workspace(ws) -> None:
    await ws.send_json({
        "messageId": "m000001",
        "kind": "request",
        "method": "workspace.status.subscribe",
        "streamId": "s000001",
        "payload": {},
    })


def test_probe_cli_prints_probe_payload(tmp_path: Path, capsys) -> None:
    path = write_config(tmp_path)

    assert main(["probe", "--config", str(path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["selfPeerId"] == "me"

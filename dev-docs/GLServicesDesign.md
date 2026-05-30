# grip-lab Services Design

Backend/services design for grip-lab — the collaborative workspace inspection &
command tool. This is the authoritative design for the non-UI side; it connects
to the front-end (already prototyped) through the protocol → grips mapping in
§15. See `dev-docs/GLRequirements.md` (requirements),
`scratch/GLRequirements-feedback.md` (decisions), and `dev-docs/GLCodingRules.md`.

Review feedback incorporated from `scratch/GLServicesDesign-Review55.md`,
`scratch/GLServicesDesign-Review55-2.md`, and `scratch/GLServicesDesign-Review55-3.md`.

**Related:** file snapshot/delta/apply, text-window projections, `FileConnection`,
and `FileWindowSubscription` are specified in `dev-docs/GLDeltaFileProtocolLib.md`.
This document covers service topology, websocket transport, watchdog tree
monitoring, command execution, and persistence.

## Status & guiding decisions

- **Security is deferred** (all collaborators trusted for now) but a single
  permission **seam** is reserved so controls slot in later without rearchitecting (§13).
- **N collaborators** from the start.
- **Async-first:** hub server and local client/server use **`asyncio` + `async def`**
  throughout (uvicorn, websockets, PTY read loops, file I/O via
  `asyncio.to_thread` where needed).
- Reuse ideas (not code-coupling) from `project_viewer.py` (PTY runs, WS
  streaming, run storage, single-instance port takeover) and
  `submodule_info_server.py` (dependency relationship scan). grip-lab must work
  on **any git repo + submodules**, with **no hard-coded workspace root**.
- Everything live is delivered as a **multiplexed subscription service** (§4);
  the UI never polls. Request/response RPC is secondary.
- The UI creates many concurrent subscriptions with independent stream identity,
  ordering, reset, backpressure, and cleanup (split editors, diff endpoints,
  session tabs, chat, presence, workspace status).

---

## 1. Topology

A **server role (hub)** and a **local client/agent** on every participating machine.

```
            ┌─────────────────────────── server (one elected node) ───────────────────────────┐
            │  hub: peer registry · message/relay bus · chat log · index · (future) auth/gate   │
            └───────▲───────────────────────▲───────────────────────────▲──────────────────────┘
                    │ ws (over ssh fwd)      │                            │
            ┌───────┴───────┐        ┌───────┴───────┐            ┌───────┴───────┐
            │ local client  │        │ local client  │   ...      │ local client  │
            │ (you)         │        │ (alice)       │            │ (bob)         │
            │ exec · monitor│        │ exec · monitor│            │ exec · monitor│
            └───────────────┘        └───────────────┘            └───────────────┘
```

- The **server** is a normal grip-lab process designated the hub.
- Each **local client** is an asyncio service bound to the machine's workspace.
  It connects **out** to the hub and serves inspection/exec for its own machine.
- **Hub required:** if the hub is down, grip-lab does **not** run anything
  peer-to-peer — clients surface "hub unreachable" and retry with backoff.
- **v1 has no client-to-client protocol.** Local clients may keep monitors and
  terminals alive while disconnected; cross-peer actions are disabled until the
  hub returns.
- Implementation: **Python asyncio**, FastAPI/uvicorn + websockets.

## 2. Connection & port model

Three ports must not be conflated:

| Port | Role | Typical value |
| --- | --- | --- |
| SSH target port | Part of the ssh connection string | `22` |
| Remote client listen port | Local client HTTP/WS on the peer machine | `3141` (default) |
| Local forwarded port | Assigned when the hub opens the ssh tunnel | ephemeral |

- Connection string: ssh target `user@host:port` (ssh port, usually 22).
- Remote client binds to **`127.0.0.1:3141`** by default.
- The hub manages ssh: open connection, local port forward to peer `:3141`,
  install/start remote client, connect over forward.
- **Prerequisite:** ssh auth (keys/agent) works; v1 does not handle interactive
  passphrase prompts.
- Absolute workspace roots stay in local git-ignored config only. Shared
  artifacts use `peerId`, `workspaceId`, `repoId`, `repoPath`, repo-relative paths.

### Connection record

```json
{
  "peerId": "alice",
  "displayName": "Alice",
  "ssh": { "user": "alice", "host": "devbox", "port": 22 },
  "workspace": { "declaredRoot": "<local-only>", "workspaceId": "alice-main" },
  "client": { "listenHost": "127.0.0.1", "listenPort": 3141, "protocolVersion": 1, "clientVersion": "0.1.0" },
  "forward": { "localHost": "127.0.0.1", "localPort": 49152 },
  "capabilities": {
    "os": "linux",
    "shells": ["bash"],
    "pty": true,
    "conpty": false,
    "git": true,
    "watchdog": true
  }
}
```

### Connection / presence states

Exposed via `presence.subscribe` (per peer) and bootstrap progress:

`unknown` · `bootstrapping` · `forwarding` · `connecting` · `online` ·
`degraded` · `offline` · `versionMismatch` · `updateFailed` · `authFailed`

The hub or local controller owns SSH forwarding process lifetime.

## 3. Deployment & lifecycle

### SSH bootstrap / update path (hub → remote over ssh)

- Connect with existing SSH credentials
- Copy or update the local client package
- Start/replace remote client (single-instance port takeover)
- Establish port forwarding
- Probe version and capabilities (`peer.probe`, `peer.bootstrap`)

### Application command path (normal operation)

- Frontend sends `cmd.run` or `term.open` over WS
- Hub routes to destination local client
- Destination local client runs under PTY/ConPTY locally
- Destination owns permission check, cwd validation, logging, interrupt, output streaming

Normal user commands **must not** run as ad hoc SSH commands after bootstrap.

- **Auto-deploy / update:** hub auto-detects remote version; missing/stale →
  auto-copy and run via single-instance takeover.
- **Cross-platform (§16):** Unix `pty`; Windows ConPTY with explicit git-bash /
  PowerShell discovery and documented resize/interrupt/encoding behavior.

## 4. Protocol

WebSocket between browser/local controller ↔ hub ↔ local clients (hub relays in v1).
All handlers are `async def`.

### Interaction shapes

- **RPC:** one-shot requests with `replyTo` correlation.
- **Subscriptions:** every live view is a **stream** with stable `streamId`.
  Begins with `snapshot` or `err`; then `delta`, `reset`, `end`, `heartbeat`.

### Message envelope

```json
{
  "v": 1,
  "msgId": "m-000001",
  "replyTo": null,
  "streamId": "s-000042",
  "kind": "req",
  "route": { "from": "me", "to": "alice" },
  "method": "file.subscribe",
  "payload": {},
  "seq": null
}
```

- `msgId` — unique per message; never overloaded as stream id.
- `streamId` — stable per subscription; null for RPC without a stream.
- `route.from` / `route.to` — origin and destination peer ids.
- `seq` — per-stream monotonic for stream events; null on RPC requests.

### Stream events

```json
{ "kind": "snapshot", "streamId": "s-000042", "seq": 0, "version": "v1", "payload": {} }
{ "kind": "delta", "streamId": "s-000042", "seq": 1, "baseVersion": "v1", "resultVersion": "v2", "payload": {} }
{ "kind": "reset", "streamId": "s-000042", "seq": 9, "version": "v9", "reason": "producer-overflow", "payload": {} }
{ "kind": "end", "streamId": "s-000042", "reason": "unsubscribed" }
{ "kind": "err", "streamId": "s-000042", "code": "not-found", "message": "File not found" }
```

Rules:

- Every delta: `seq`, `baseVersion`, `resultVersion` (and content hashes in payload).
- Consumer checks seq and base version/hash; mismatch → resubscribe or
  close/reopen the stream (see `GLDeltaFileProtocolLib.md`).
- `reset` is normal, not exceptional.
- Producer bounded queues; lagging consumer → drop queued deltas, send `reset`.
- Reconnect: resubscribe; request `resumeFrom` if supported, else fresh snapshot.
- Stream errors scoped to `streamId`; connection-level errors use `streamId: null`.

### Filedelta → websocket mapping

| Filedelta callback | WS event |
| --- | --- |
| `on_listening` | optional `progress`, or omitted |
| `on_snapshot` | `snapshot` |
| `on_delta` | `delta` |
| `on_reset` | `reset` |
| `on_error` | `err` |
| `on_stop_listening` | `end` |

The websocket layer owns per-subscriber queue limits. Filedelta emits sequential
deltas; WS decides when a lagging browser subscriber gets `reset`.

### Endpoints (methods)

**Peer and connection**

| Method | Shape | Purpose |
| --- | --- | --- |
| `peer.probe` | req | Pre-registration health check (OS, shells, workspace) |
| `peer.bootstrap` | req | Install/start remote client + forward |
| `peer.update` | req | Force client update |
| `peer.hello` / `peer.bye` | req | Running client registers with hub |
| `peer.capabilities` | req | PTY, ConPTY, git, watchdog, path behavior |
| `peer.remove` | req | Remove peer from local config |
| `presence.subscribe` | sub | Connection states (§2) per peer |

**Workspace**

| Method | Shape | Purpose |
| --- | --- | --- |
| `workspace.status.subscribe` | sub | Repo git status image + deltas |
| `workspace.status.refresh` | req | Force git reconciliation |
| `deps.get` | req | Cached dependency graph |

**Tree and files**

| Method | Shape | Purpose |
| --- | --- | --- |
| `tree.subscribe` / `tree.unsubscribe` | sub | Watchdog-backed workspace tree |
| `tree.search` | req | Indexed path search (large repos) |
| `tree.refresh` | req | Explicit tree reconciliation |
| `file.subscribe` / `file.unsubscribe` | sub | File stream; see §5 for content modes |
| `file.window.update` | req | Grow/shrink/move line window on open stream |
| `file.snapshot` | req | One-shot full or window snapshot for recovery |

**Diff**

| Method | Shape | Purpose |
| --- | --- | --- |
| `diff.subscribe` / `diff.unsubscribe` | sub | Hub-owned synthetic live structured diff stream |
| `diff.window.update` | req | Grow/shrink/move the source line window for an open diff stream |
| `diff.get` | req | One-shot diff/export/historical comparison; same payload shape as live diff |

**Commands, sessions, terminals**

| Method | Shape | Purpose |
| --- | --- | --- |
| `cmd.run` | req→events | Create session and start targets |
| `cmd.interrupt` | req | Interrupt/terminate/kill target or session |
| `sessions.subscribe` | sub | Session list changes (canonical after reconnect) |
| `session.subscribe` | sub | One session metadata + targets |
| `session.output.subscribe` | sub | Output stream for one target (live or stored) |
| `sessions.query` | req | grepsql (§8) |
| `sessions.hide` / `sessions.purge` | req | Hide / age purge |
| `term.open` / `term.input` / `term.resize` / `term.close` | sub+req | Interactive PTY |

**Chat**

| Method | Shape | Purpose |
| --- | --- | --- |
| `chat.subscribe` / `chat.post` | sub/req | Hub-ordered messages; post returns authoritative id |

`cmd.run` returns the authoritative `sessionId` and may stream immediate
lifecycle events, but the UI must reconstruct all visible session state from
`sessions.subscribe`, `session.subscribe`, and `session.output.subscribe` after
reconnect. Creating a run is separate from viewing stored session output.

## 5. File content streams & tree monitoring

### File content (`filedelta` + service layer)

Full protocol in `dev-docs/GLDeltaFileProtocolLib.md`. Summary:

- **`FileConnection`** — source file, `fileVersion`; receives `file_changed()`
- **`FileWindowSubscription`** — projected line window, `windowVersion`, `seq`;
  receives `update_window()`
- Text-window streams carry byte deltas against the **current window blob**, not
  necessarily the whole file

#### `file.subscribe`

Opens a stream for one `(peer, workspaceId, repoPath, path, ref)` endpoint.

```json
{
  "peerId": "alice",
  "workspaceId": "alice-main",
  "repoPath": "yidl",
  "path": "src/yidl/cli.py",
  "ref": { "kind": "working" },
  "contentMode": "text-window",
  "window": {
    "lineStart": 0,
    "lineEnd": 240,
    "overscanBefore": 40,
    "overscanAfter": 80
  }
}
```

`contentMode`: `"full"` | `"text-window"` | `"metadata-only"`.

- **`text-window`** (default for editor): projected line range; byte payload;
  grow/shrink via `file.window.update`
- **`full`**: whole-file snapshot/deltas (small files, tests)
- **`metadata-only`**: size/kind/git metadata only (large/binary)

`lineStart`/`lineEnd` are zero-based, half-open internally. Ref kinds: `working`,
`head`, `{ kind: "commit", oid }`. `head` streams reset on HEAD move.

#### `file.window.update`

Subscription projection change — **not** a filesystem event:

```json
{
  "streamId": "s-file-1",
  "window": {
    "lineStart": 180,
    "lineEnd": 520,
    "overscanBefore": 60,
    "overscanAfter": 120
  }
}
```

Routed to `FileWindowSubscription.update_window()`, not `file_changed()`.

#### Event routing

```text
watchdog event       → FileConnection.file_changed("watchdog")
git HEAD move        → FileConnection.file_changed("head")
file.window.update   → FileWindowSubscription.update_window()
```

Service layer maps filedelta callbacks to websocket stream events (§4).

#### Subscription deduplication (browser client)

Two dedup keys:

- **Source key:** `(peerId, workspaceId, repoPath, path, ref)`
- **Window key:** source key + requested window/projection

**v1:** one projected stream per editor column/window (simpler). Later:
merge overlapping windows into one larger server window and slice locally.

Taps subscribe to a file view; they must not assume the first payload is the
whole file.

### Tree monitor (service layer, not filedelta)

Separate live resource for the Files explorer. Uses **watchdog** directly.

Tree streams report path existence and basic file metadata. Workspace status
streams report git/repo state. A single filesystem event may invalidate both,
but **each stream snapshots/resets independently** — a tree reset does not imply
git status reset, and vice versa. Branch checkout may cause both.

Example tree snapshot:

```json
{
  "workspaceId": "alice-main",
  "version": "tree-v1",
  "repos": [
    { "repoId": "root", "repoPath": "", "name": "project" },
    { "repoId": "yidl", "repoPath": "yidl", "name": "yidl" }
  ],
  "entries": [
    { "repoId": "yidl", "path": "src/yidl/cli.py", "kind": "file", "size": 1200, "mtimeNs": 1 }
  ],
  "truncated": false,
  "ignored": ["node_modules", "dist"]
}
```

Tree deltas: `upsertEntry`, `removeEntry`, `moveEntry`, `resetRepo`.

Watchdog: one recursive observer per workspace root; ignore `.git`, `.grip-lab`,
`.grip-lab-hub`, `node_modules`, `dist`, `__pycache__`, venvs; debounce;
reconcile; overflow → `resetRepo`. Git status: event-driven invalidation +
coalesced refresh, not on every file event.

## 6. Workspace status

`workspace.status.subscribe` includes per-repo **errors** (missing submodule,
not initialized, unreadable).

```json
{
  "workspaceId": "alice-main",
  "repos": [
    {
      "repoId": "repo-yidl",
      "repoPath": "yidl",
      "name": "yidl",
      "identity": { "remoteUrlHash": "sha256:...", "worktreeKind": "submodule" },
      "branch": "feature/parser",
      "head": "1122334",
      "upstream": "origin/feature/parser",
      "ahead": 3,
      "behind": 1,
      "dirty": true,
      "changedFiles": [{ "path": "src/yidl/concept_parser.py", "change": "modified" }],
      "error": null
    }
  ]
}
```

v1 recurses submodules one level; deeper nesting: include, omit with reason, or
depth limit.

## 7. Persistence & grepsql

### Layout (executor-side)

```text
.grip-lab/
  index.json                 # rebuildable cache
  sessions/
    <session-id>/
      session.json
      events.jsonl           # append-only lifecycle
      targets/
        <target-id>/
          meta.json
          output.log         # raw bytes, not assumed UTF-8
          diagnostics.json
  deps.json
```

Directory names use stable ids and sanitized slugs.

### Layout (hub-side)

```text
.grip-lab-hub/
  index.json
  chat/<hub-time-ns>-<counter>-<sender-peer-id>.json
```

### Writes

- JSON metadata; atomic replace; index is rebuildable cache
- Session persisted **before** process starts
- Chat: temp → fsync → rename → index update or rebuild

### grepsql v1

```json
{
  "text": "AssertionError",
  "peers": ["alice"],
  "repos": ["yidl"],
  "status": ["error"],
  "includeHidden": false,
  "limit": 100
}
```

Search on executor; hub fans out and merges.

## 8. Command execution & terminals

### Request shape

```json
{
  "targetPeerId": "alice",
  "workspaceId": "alice-main",
  "repos": ["yidl", ""],
  "cwd": { "mode": "repoRoot" },
  "command": {
    "mode": "argv",
    "argv": ["uv", "run", "pytest", "-q"]
  },
  "env": {},
  "pty": { "cols": 120, "rows": 30 },
  "requestContext": {
    "requesterPeerId": "me",
    "source": "sessions-view"
  }
}
```

Shell mode is explicit opt-in. Do not split whitespace for argv mode.

### Lifecycle events (`cmd.run` convenience stream)

```json
{ "event": "accepted", "sessionId": "sess-1" }
{ "event": "targetQueued", "targetId": "t-1", "repoPath": "yidl" }
{ "event": "targetStarted", "targetId": "t-1", "pid": 1234 }
{ "event": "output", "targetId": "t-1", "seq": 1, "bytes": "base64:..." }
{ "event": "targetExited", "targetId": "t-1", "exitCode": 0, "durationMs": 1200 }
{ "event": "diagnosticsReady", "targetId": "t-1" }
{ "event": "sessionFinished", "status": "ok" }
```

**State ownership:** `sessions.subscribe` is canonical for session-list updates;
`session.subscribe` for one session's metadata; `session.output.subscribe` for
target output. `cmd.run` events are immediate convenience; reconnect uses
session subscriptions.

### Interrupt

```json
{ "sessionId": "sess-1", "targetId": "t-1", "mode": "interrupt" }
```

Modes: `interrupt` · `terminate` · `kill`.

### Terminal persistence

Interactive terminals (`term.*`) follow the same session model:

- Terminal has a `sessionId` and `targetId`
- Raw PTY output is persisted to `output.log` (bytes)
- Terminal input may be audited separately or omitted (policy TBD; document explicitly)
- `term.close` writes a terminal-ended event and close metadata to `events.jsonl`
- Stored terminal output reads through the same renderer as command sessions

All exec through permission seam (§13).

## 9. Dependency graph discovery

Infrequent cached scan (model: `submodule_info_server.py` → `deps.json`).
Recompute on demand or when `.gitmodules`/manifests change — never per render.

## 10. Repo identity & workspace discovery

One workspace root per peer; root + submodules (one level v1). Same repos assumed;
verified by remote URL hash. Missing repo → "not present".

## 11. Chat & links

Validated link payloads (see `dev-docs/StateLinks.md`). `chat.post` returns
hub-assigned authoritative message. Diff links: `HEAD` = live; commit oid = pinned.

## 12. Hub loss & reconnection

- Global hub status: `up | unreachable`; disables cross-peer actions.
- Exponential-backoff reconnect; resubscribe all streams.
- Active commands during hub drop: executors continue running and logging;
  cross-peer visibility stops until hub returns.

## 13. Permission seam (security deferred)

Destination local client is the authority.

```python
decision = await check_permission(context)  # always allow in v1
```

Context: requester/target peer, action, workspaceId, repoPaths, cwd, command mode,
argv or shell line, env, file path + ref, interactive flag, source link/session.

v1 safeguards: loopback bind, path traversal rejection, repo/path validation,
audit log.

## 14. Browser-side service client

One browser module owns websocket mechanics. Taps stay thin.

- Single websocket connection; route/method helpers; stream id allocation
- Subscription ref-counting; **two-level dedup** (source key + window key)
- Reconnect, resubscribe, snapshot/delta/reset handling
- **Windowed files:** track viewport from file taps; debounce scroll-driven
  `file.window.update`; keep applied window blob + metadata per stream; decode
  bytes to text only after validated delta apply
- Typed decoding; optional render coalescing

Protocol models: pydantic Python + TypeScript interfaces, tested together.

## 15. Front-end mapping (protocol → grips/taps)

- `FileContentTap`: `file.subscribe` (`contentMode: text-window`) per column →
  `FILE_CONTENT` / `FILE_GIT_STATUS`; scroll triggers debounced `file.window.update`
- `SessionOutputTap`: `session.output.subscribe` → `SESSION_OUTPUT` / `SESSION_DIAGNOSTICS`
- Tree explorer: `tree.subscribe`
- Workspace: `workspace.status.subscribe`
- Chat: `chat.subscribe`
- Diff view: `diff.subscribe` synthetic structured diff stream; see
  `dev-docs/GLDiffStreamDesign.md`

The hub, not the browser, owns live diff source subscriptions in service mode.
The browser renders structured hunks and sends `diff.window.update` for scroll
or window changes.

## 16. Cross-platform notes

- Unix: `pty` + process groups
- Windows: ConPTY preferred; git-bash and PowerShell; explicit terminal semantics
- Paths: forward slashes internally; no absolute machine paths in shared artifacts

## 17. Implementation order

1. Protocol models (Python + TypeScript) with stream lifecycle tests
2. Standalone **`filedelta`** per `GLDeltaFileProtocolLib.md` (full + text-window)
3. Single-machine asyncio local client: tree, file window streams, workspace status, PTY
4. Browser service client (incl. window update debouncing) + replace mock taps
5. Hub routing, peer registry, presence
6. SSH bootstrap/update/forwarding
7. Chat persistence and session query
8. Cross-peer diff and cross-peer command execution

## 18. Resolved decisions

| Topic | Decision |
| --- | --- |
| Async runtime | asyncio + async def for hub and local client |
| File delta library | Separate `filedelta`; see `GLDeltaFileProtocolLib.md` |
| Text editor mode | `text-window` default; byte deltas on window blob |
| Window updates | `file.window.update` RPC; not `file_changed()` |
| FileConnection split | Source connection + per-subscriber window subscription |
| Stream mapping | Filedelta callbacks → WS events; WS owns backpressure |
| Dedup v1 | One projected stream per editor column |
| Session state | Session subscriptions canonical after reconnect |
| Terminal persistence | Same session model; output.log + events.jsonl |
| Tree vs status | Independent stream reset |
| Hub failover | None in v1 |
| SSH vs app exec | SSH bootstrap only; commands via destination PTY |

## 19. Still open (minor)

- Default watchdog ignore list per ecosystem
- Whether `deps.subscribe` needed in v1
- Exact `fullContentSizeCap` / `windowBytesCap`
- Terminal input audit policy
- Property-test library choice under dependency-age policy

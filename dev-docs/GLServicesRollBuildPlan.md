# GLServices Roll-Build Plan

Implementation plan for the services described in `dev-docs/GLServicesDesign.md`.

This plan assumes `dev-docs/GLDeltaFileWindowProtocolPlan.md` is implemented far
enough to provide the `filedelta` Python package and TypeScript reassembler.

This is a roll-build-compatible plan. Start only from a clean working tree,
choose a phase-start tag, implement one phase at a time, and commit/tag only
when the phase goal is met and focused verification passes.

## Readiness

The services design is ready for planning. The remaining open items are phase
parameters, not blockers:

- whether `deps.subscribe` is needed in v1

## Local Dev Workflow

Initial local development runs hub, one local client, and the Vite UI:

```text
griplab hub --config .grip-lab/local/hub.json
griplab client --config .grip-lab/local/client.json
npm run dev
```

`.grip-lab/local/` is local and git-ignored. The exact command runner can be
refined during Phase 1, but the three-process workflow is the target.

## Source Location

Python backend source belongs under top-level `services/`, separate from the
existing frontend `src/` tree:

```text
grip-lab/
  src/                         # existing React/TypeScript frontend only
  services/
    filedelta/                 # pure, excisable Python delta library
      pyproject.toml
      src/filedelta/
      tests/
    griplab_service/           # hub/local-client service
      pyproject.toml
      src/griplab_service/
      tests/
```

Rules:

- Do not place Python backend modules under frontend `src/`.
- `services/filedelta` must remain service-independent.
- `services/griplab_service` may import `filedelta` and owns watchdog, git,
  websocket, PTY/ConPTY, SSH bootstrap, persistence, and permission checks.
- Shared TypeScript protocol/client code can live either in the frontend package
  or a later `services/*-ts` package, but Python remains under `services/`.

## Runtime Module Map

Initial `services/griplab_service/src/griplab_service/` module layout:

```text
griplab_service/
  __init__.py
  cli.py                  # `griplab hub`, `griplab client`
  config.py               # local config schema and load/save
  protocol/
    __init__.py
    envelope.py
    streams.py
    peer.py
    workspace.py
    tree.py
    file.py
    sessions.py
    chat.py
    errors.py
  hub/
    __init__.py
    app.py                # FastAPI/WS app factory for hub mode
    registry.py
    relay.py
    chat_store.py
    query_fanout.py
  local_client/
    __init__.py
    app.py                # FastAPI/WS app factory for local client mode
    lifecycle.py          # single-instance takeover
    workspace.py
    git_status.py
    tree_watch.py
    file_streams.py
    sessions_store.py
    exec_pty.py
    terminal.py
    permissions.py
  ssh_bootstrap.py
  paths.py
  atomic_io.py
```

Entrypoints:

- `griplab hub --config <path>`
- `griplab client --config <path>`
- `griplab probe --config <path>`

The same package can run hub mode or local-client mode, but the mode must be an
explicit CLI command, not an implicit environment side effect.

## Local Config Shape

Config is local and git-ignored. It may contain machine-specific absolute
workspace roots. Shared artifacts must continue to use peer/workspace/repo ids
and repo-relative paths.

```json
{
  "selfPeerId": "me",
  "mode": "client",
  "listen": { "host": "127.0.0.1", "port": 3141 },
  "workspace": {
    "workspaceId": "local-main",
    "root": "<local absolute path allowed only in config>"
  },
  "peers": [
    {
      "peerId": "alice",
      "displayName": "Alice",
      "ssh": { "user": "alice", "host": "devbox", "port": 22 },
      "workspaceId": "alice-main"
    }
  ]
}
```

## Architecture Target

```text
browser service client
  |
  +- GRIP taps
  |
  +- websocket
       |
       v
hub service
  +- peer registry
  +- stream relay
  +- chat store
  +- session/query fanout
       |
       v
local client service
  +- workspace discovery
  +- watchdog tree monitor
  +- filedelta integration
  +- git status monitor
  +- PTY/ConPTY command execution
  +- executor-owned session store
```

## Protocol Model Scope

Implement shared protocol data structures before handlers:

- message envelope
- stream events
- routing
- peer records and presence states
- workspace status snapshots/deltas
- tree snapshots/deltas
- file subscribe/window update requests
- command/session/terminal events
- chat messages and link payloads
- error payloads

Python should own runtime validation for backend inputs. TypeScript should own
runtime validation for websocket payloads before updating GRIP values.

## Roll-Build Phases

### Phase 0: service skeleton and protocol models

Goal:

- Establish service package layout and typed protocol models without real peer
  networking.

Deliverables:

- `services/griplab_service/pyproject.toml`
- `services/griplab_service/src/griplab_service/` package skeleton
- protocol model module
- TypeScript protocol interfaces/validators
- in-process or local websocket test harness
- basic stream event encode/decode tests

Verification:

- `uv run pytest services/griplab_service/tests/test_protocol*.py`
- TypeScript protocol tests pass (exact command pinned when TS location is chosen)
- no absolute paths in committed examples/docs

Exit criteria:

- message envelope and stream events round-trip in Python and TypeScript
- malformed messages are rejected

### Phase 1: single-machine local service

Goal:

- Run a local asyncio service bound to one declared workspace root.

Deliverables:

- local service startup
- loopback bind
- health endpoint
- workspace config loading
- single-instance takeover skeleton
- version/capability probe

Verification:

- `griplab client --config <fixture-config>` starts and stops cleanly
- probe returns OS/shell/git/watchdog capability fields
- local-only absolute workspace root is not written to shared artifacts

Exit criteria:

- one local client can be probed by the browser/dev harness

### Phase 2: workspace discovery and git status stream

Goal:

- Discover root repo plus v1 submodules and publish workspace status.

Deliverables:

- repo discovery from declared root
- submodule enumeration one level deep
- remote identity hash
- git porcelain/plumbing status collection
- `workspace.status.subscribe`
- `workspace.status.refresh`
- per-repo error states

Verification:

- tests with temp git repos and submodules where feasible
- missing/uninitialized submodule case
- status stream snapshot and delta/reset tests

Exit criteria:

- Workspace view can replace mock repo status for local peer

### Phase 3: dependency graph scan

Goal:

- Implement `deps.get` for the workspace graph view.

Deliverables:

- `.gitmodules` scan
- root + submodule dependency graph model
- cached `deps.json`
- explicit refresh path
- graceful unknown/missing relationship handling

Verification:

- temp fixture or static fixture with root + submodules
- cache rebuild test
- missing `.gitmodules` test

Exit criteria:

- Workspace graph can use service dependency data instead of mock dependencies

### Phase 4: watchdog tree stream

Goal:

- Provide live file explorer data independent of git status.

Deliverables:

- watchdog adapter
- default ignore policy: `.git`, `.grip-lab`, `.grip-lab-hub`, `node_modules`,
  `dist`, `__pycache__`, virtualenv directories
- debounce/reconcile loop
- tree snapshot
- tree deltas: `upsertEntry`, `removeEntry`, `moveEntry`, `resetRepo`
- `tree.subscribe`, `tree.unsubscribe`, `tree.refresh`

Verification:

- temp directory tests: create, modify, delete, rename, nested dirs
- ignored paths do not publish
- overflow/mass-change path emits reset

Exit criteria:

- File explorer can replace `WORKSPACE_FILES` for local peer

### Phase 5: file window stream integration

Goal:

- Wire service `file.subscribe` and `file.window.update` to `filedelta`.

Deliverables:

- source/window subscription registry
- file stream websocket mapping
- `file.subscribe`
- `file.window.update`
- `file.unsubscribe`
- `file.snapshot`
- browser service client support for file windows
- GRIP `FileContentTap` replacement for local peer

Phase 5 introduces a minimal file-only browser service client slice. Phase 8
generalizes that seed into the full service client for workspace, tree,
sessions, chat, reconnect, and shared subscription management. Do not create a
separate competing client in Phase 5.

File stream caps come from `dev-docs/GLDeltaFileWindowProtocolPlan.md`
(`fullContentSizeCap`, `windowBytesCap`, delta/reset thresholds).

Verification:

- focused service tests for start/reset/grow/shrink/window update routing
- browser-side test with generated fixtures from `filedelta`
- manual local file open updates after edit

Exit criteria:

- Files view can show local text-window file content from service
- scroll/window update path works through service client

### Phase 6: command execution, terminals, and session store

Goal:

- Implement local command and terminal execution with executor-owned logs.

Deliverables:

- session store layout
- atomic metadata writes
- append-only `events.jsonl`
- PTY execution on Unix
- command request validation
- `cmd.run`
- `cmd.interrupt`
- `term.open`
- `term.input`
- `term.resize`
- `term.close`
- `sessions.subscribe`
- `session.subscribe`
- `session.output.subscribe`
- terminal persistence policy implemented (v1: persist raw output; do not persist
  input unless audit policy is explicitly enabled)
- diagnostics parser hook

Verification:

- command runs in repo root
- multi-repo command creates one session with multiple targets
- output is raw bytes and can be replayed
- interrupt works on running process
- interactive terminal opens, receives input, resizes, closes, and replays output
- session list reconstructs after service restart

Exit criteria:

- Sessions view can replace mock command sessions for local peer

### Phase 7: sessions query / grepsql

Goal:

- Implement query over executor-owned session metadata and output.

Deliverables:

- `sessions.query`
- metadata prefilter
- output grep over `output.log`
- hidden/session status filters
- result summaries mapped back to session ids

Verification:

- query by command text
- query by output text
- query by peer/repo/status
- hidden sessions excluded unless requested

Exit criteria:

- Sessions search can use backend query for local peer

### Phase 8: browser service client and GRIP tap replacement

Goal:

- Replace mock data flows for local peer through a single browser service client.

Deliverables:

- websocket client module
- stream id allocation
- subscription ref-counting
- reconnect/resubscribe
- snapshot/delta/reset handling
- render coalescing if needed
- taps for workspace, tree, file, sessions, chat placeholder

Verification:

- component smoke test or browser manual test
- reconnect test against local service restart
- multiple editor columns do not corrupt one another

Exit criteria:

- local single-machine app is usable without mock data for core workspace,
  files, and sessions

### Phase 9: hub service and peer registry

Goal:

- Introduce hub routing while still using local/loopback peers.

Deliverables:

- hub startup
- peer registry
- local client registers with `peer.hello`
- presence stream
- stream relay
- route validation
- hub loss/reconnect behavior

Verification:

- two local clients can register to hub using different workspace roots or test
  fixtures
- presence updates on disconnect/reconnect
- stream relay preserves stream ids and errors

Exit criteria:

- browser can view local service through hub route

### Phase 10: SSH bootstrap and forwarding

Goal:

- Add remote peer bootstrap/update path.

Deliverables:

- `peer.probe`
- `peer.bootstrap`
- parse SSH target
- copy/install local client package
- start remote client
- establish local port forward
- version check and auto-update
- connection state reporting
- failure states: auth failed, update failed, version mismatch

Verification:

- local SSH fixture where available
- command logs show bootstrap actions
- remote service binds loopback
- stale client update path tested with fake versions

Exit criteria:

- collaborator can be added through SSH-forwarded local client

### Phase 11: chat store and links

Goal:

- Implement hub-ordered chat with validated links.

Deliverables:

- `chat.post`
- `chat.subscribe`
- hub-assigned message ids
- one JSON file per message
- atomic writes
- rebuildable chat index
- link schema validation
- browser tap replacement for chat messages

Verification:

- lexicographic message order
- malformed links rejected
- index rebuild from files
- chat links still apply GRIP state

Exit criteria:

- Chat panel uses hub-backed messages and links

### Phase 12: cross-peer workspace, file, diff, command

Goal:

- Enable the collaborative cross-machine behavior.

Deliverables:

- cross-peer workspace status
- cross-peer file window streams
- client-derived diff from two file streams
- remote `cmd.run` through destination permission seam
- remote session output subscription

Verification:

- two peers with same repo identity show status differences
- file viewer can switch peers
- diff view compares two peers/refs
- remote command stores logs on executor
- hub reconnect reconciles running command state

Exit criteria:

- end-to-end collaborative workflow works for two peers

### Phase 13: hardening and polish

Goal:

- Stabilize before broader use.

Deliverables:

- path traversal tests
- permission audit log
- caps and defaults finalized
- watchdog ignore list tuned
- Windows ConPTY implementation or explicit unsupported state
- docs for local dev and operation

Verification:

- focused security/path tests
- long-running command smoke
- large file/window cap behavior
- app build/lint/test

Exit criteria:

- ready for broader manual testing

## Dependency On Delta Plan

Minimum `filedelta` readiness before Phase 5:

- Python text-window snapshots/deltas
- Python async `FileConnection` and `FileWindowSubscription`
- TS reassembler
- shared fixture tests for start/reset/grow/shrink/changed/inserted/removed/truncated

Do not start service file-window integration until the cross-language fixture
tests pass. Otherwise service bugs and protocol bugs will be hard to separate.

## Roll-Build Guardrails

Pause before the next phase if:

- the current phase cannot be verified without implementing the next phase
- remote SSH behavior requires unclear credential handling
- file window protocol changes invalidate service assumptions
- command execution semantics differ across platforms more than documented
- session persistence cannot reconstruct after restart
- hub reconnect loses authoritative state

## Verification Commands

The old front-end commands remain relevant once the React app is in the working
tree:

- `npm run build`
- `npm run lint`
- `npm test`

Add service-specific commands as the Python package lands:

- focused Python tests for service modules
- focused TypeScript tests for protocol/client modules
- end-to-end local service smoke test

## Planning Status

Ready for roll-build planning after the delta file window protocol plan enters
implementation or reaches its minimum readiness checkpoint.

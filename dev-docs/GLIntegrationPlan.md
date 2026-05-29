# GLIntegrationPlan

Plan for integrating the grip-lab service protocol with the current React/GRIP
UI in `src/` while keeping the existing mock/test app intact.

## Goals

- Keep the current mock taps and fake data available for UI testing, demos, and
  offline iteration.
- Add a parallel server-fed tap set that uses the same public UI grips where
  possible, so components move to service data by selecting a tap bundle rather
  than rewriting view code.
- Use `createAsyncMultiTap<Outs, any>` for every non-trivial server-fed tap.
- Put each non-trivial service tap in its own `.ts` file.
- Keep websocket ownership centralized in one browser service client module.
- Preserve child-context file viewer behavior: each editor column owns its file
  destination params and receives independent file content.

## Current UI Facts

The current app registers mock taps from `src/lab/taps.ts`.

Important existing seams:

- `registerLabTaps()` registers local atom taps plus mock data taps.
- `registerFileContentTap()` in `src/lab/fileContentTap.ts` is already a
  per-destination tap: it reads `ACTIVE_FILE` and `FILE_REF` from the editor
  column child context and home params from the main context.
- `registerSessionOutputTap()` derives output/diagnostics from mock `SESSIONS`.
- `FileExplorer` still imports `WORKSPACE_FILES` directly; it needs a grip-fed
  tree before the server app can be fully data-driven.
- Local UI state grips and backend data grips are currently mixed in
  `src/lab/grips.ts`.

## Non-Goal

Do not delete or replace the current mock taps during service integration. The
mock/test app remains the reference harness for UI behavior.

## App Modes

Add an explicit tap-bundle selection in bootstrap:

```text
VITE_GL_DATA=mock     # default: current mock/test app taps
VITE_GL_DATA=service  # server-fed app taps
```

`VITE_GL_UI` continues to select the surface (`lab` vs `hello`). `VITE_GL_DATA`
selects the data/tap bundle for the lab surface.

Registration shape:

```ts
registerAllTaps();

if (surface === 'lab') {
  if (dataMode === 'service') registerLabServiceTaps();
  else registerLabMockTaps();
}
```

Rename-only cleanup is acceptable:

- Current `registerLabTaps()` may become `registerLabMockTaps()`.
- Export `registerLabTaps` as an alias during migration if useful.

## Source Layout

Keep the existing mock files in place. Add service integration under
`src/lab/serviceClient/`.

```text
src/lab/
  taps.ts                         # mock/test tap registration remains
  fileContentTap.ts               # mock file content tap remains
  sessionOutputTap.ts             # mock session output tap remains
  serviceClient/
    index.ts
    registerLabServiceTaps.ts
    client.ts                     # one websocket client owner
    streamStore.ts                # stream id allocation, replay, ref counts
    protocol.ts                   # browser-side protocol types/validators
    requestKeys.ts                # stable key builders for async taps
    filedelta/
      index.ts                    # imports/re-exports TS filedelta package
    taps/
      serviceStateTap.ts
      peersTap.ts
      workspaceStatusTap.ts
      depsGraphTap.ts
      treeTap.ts
      fileContentTap.ts
      sessionsTap.ts
      sessionOutputTap.ts
      chatMessagesTap.ts
      probeTap.ts
```

If TypeScript filedelta support remains in `services/filedelta-ts`, import from
that package through `serviceClient/filedelta/index.ts`. If it is later folded
into frontend source, this adapter keeps the rest of the UI stable.

## Shared Service Client

One module owns websocket mechanics:

```text
ServiceClient
  connect()
  close()
  request(method, payload, signal)
  subscribe(method, payload, handlers, signal)
  unsubscribe(streamId)
```

Responsibilities:

- websocket URL and connection state
- stream id allocation
- request id allocation
- reconnect and resubscribe
- protocol envelope validation
- fanout to tap-local subscribers
- backpressure/drop/reset policy handoff
- debug logging tags

Taps call this client; taps do not create websocket connections directly.

## Local UI Taps That Remain Atom Taps

These remain in both mock and service modes because they are local UI state:

- `CURRENT_VIEW`
- `THEME`
- `WORKSPACE_LAYOUT`
- `WORKSPACE_MENU`
- `SELECTED_PEER_ID`
- `SELECTED_FILE`
- `EDITOR_GROUPS`
- `ACTIVE_GROUP`
- `FOCUS_LINE`
- `DIFF_LEFT`
- `DIFF_RIGHT`
- `CHAT_DRAFT`
- `CHAT_PENDING`
- `CHAT_PANEL_OPEN`
- `CHAT_PANEL_WIDTH`
- `CHAT_PANEL_DRAGGING`
- `CHAT_COMPOSER_H`
- `CHAT_COMPOSER_DRAG`
- `EXPLORER_COLLAPSED`
- `EXPLORER_OPEN`
- `EXPLORER_WIDTH`
- `EXPLORER_DRAG`
- `ONBOARDING_FORM`
- `COLLAB_EDIT`
- `AVATAR_EDIT`
- `SELECTED_SESSION`
- `SESSION_SEARCH`
- `SESSION_FILTERS`
- `SESSION_DRAFT`
- `SELECTED_TARGET`
- `RUN_REPOS`
- `RUN_REPOS_OPEN`
- `PURGE_DAYS`
- `RUN_DIALOG_OPEN`
- `FILE_REF`
- `ACTIVE_FILE`

Service mode can still write some of these through command handlers, but their
primary ownership is the browser UI.

## New or Clarified Grips

Add these grips before service taps land:

- `SERVICE_CONNECTION`: connection status, current endpoint, last error
- `SERVICE_CONNECTION_TAP`: optional handle for reconnect/manual endpoint
- `WORKSPACE_STATUS`: service-owned repo status list
- `WORKSPACE_STATUS_TAP`: only if the UI needs local override/debug actions
- `WORKSPACE_TREE`: normalized file tree entries from `tree.subscribe`
- `WORKSPACE_TREE_VERSION`: tree version/debug marker
- `DEPS_GRAPH`: dependency graph data for `WorkspaceGraphView`
- `FILE_WINDOW`: per-destination requested line window for file content
- `FILE_WINDOW_TAP`: per-destination handle used by editor viewport changes
- `FILE_STREAM_STATUS`: per-destination file stream state/error
- `FILE_LINE_INDEX`: per-destination line offsets from filedelta
- `SESSION_OUTPUT_STATUS`: selected output stream status/error
- `CHAT_STREAM_STATUS`: chat stream status/error

Existing grips reused by service taps:

- `PEERS`
- `FILE_CONTENT`
- `FILE_GIT_STATUS`
- `GRAPH_NODES` or a later graph data grip
- `SESSIONS`
- `SESSION_OUTPUT`
- `SESSION_DIAGNOSTICS`
- `CHAT_MESSAGES`

## Tap Bundle: Mock

Keep the current mock behavior in a dedicated registration function:

```text
registerLabMockTaps()
```

It registers:

- all local UI atom taps
- `registerGraphSimTap()`
- existing mock `registerFileContentTap()`
- existing mock `registerSessionOutputTap()`
- mock atom taps for `PEERS`, `CHAT_MESSAGES`, `SESSIONS`

The mock bundle may continue to import `fakeData.ts`.

## Tap Bundle: Service

Add:

```text
registerLabServiceTaps()
```

It registers:

- the same local UI atom taps as the mock bundle
- service-backed async taps listed below
- optional placeholder/mock taps only for phases not yet implemented

Do not register mock and service providers for the same output grip in the same
runtime. Choose one bundle at bootstrap.

## Service Tap Pattern

Every non-trivial service tap uses:

```ts
createAsyncMultiTap<Outs, any>({
  provides,
  destinationParamGrips,
  homeParamGrips,
  requestKeyOf,
  fetcher,
  mapResult,
})
```

For stream subscriptions, `fetcher` may call the shared service client's
`subscribeSnapshot()` helper, which returns the current materialized stream
state after receiving the first snapshot. The helper owns async cancellation and
unsubscribes when the tap request is aborted.

For long-lived streams, the returned result should be the materialized current
state plus a subscription handle managed by `streamStore`. Subsequent websocket
events update the same grip outputs by forcing tap production or through the
service client's approved GRIP update mechanism. The implementation phase must
choose one mechanism and test reconnect behavior.

## Taps To Generate

### `serviceStateTap.ts`

Purpose:

- Publish connection state and capability status.

Provides:

- `SERVICE_CONNECTION`

Params:

- none initially, or endpoint config grip if one is added

Protocol:

- `peer.probe` or local client health/probe endpoint

Tests:

- disconnected state when endpoint missing
- connected state maps capability fields
- failed probe maps stable error payload
- abort signal cancels in-flight probe

### `peersTap.ts`

Purpose:

- Publish collaborator list and presence from hub/local registry.

Provides:

- `PEERS`

Params:

- optional selected workspace/hub endpoint

Protocol:

- `peer.presence.subscribe`
- `peer.hello` side effects are service startup responsibilities, not this tap

Tests:

- initial peer snapshot maps to current `Peer` shape
- presence delta updates `online`
- self peer maps `isSelf`
- malformed peer record rejected
- reconnect resubscribes once

### `workspaceStatusTap.ts`

Purpose:

- Replace mock workspace status data for `WorkspaceStatusView`.

Provides:

- `WORKSPACE_STATUS`

Eventually may also provide:

- repo errors/status summary grips if split out

Params:

- `SELECTED_PEER_ID`

Protocol:

- `workspace.status.subscribe`
- `workspace.status.refresh` via service client command helper, not the tap
  fetcher unless refresh is represented as a grip parameter

Tests:

- snapshot maps root repo and submodule statuses
- dirty/ahead/behind/changed files preserved
- repo error states preserved
- delta/reset updates materialized status
- selected peer changes subscription key

### `depsGraphTap.ts`

Purpose:

- Provide dependency graph data for `WorkspaceGraphView`.

Provides:

- `DEPS_GRAPH`
- possibly `GRAPH_NODES` during transition

Params:

- `SELECTED_PEER_ID`
- `WORKSPACE_LAYOUT` only if graph output depends on layout mode

Protocol:

- `deps.get`
- optional future `deps.subscribe`

Tests:

- root + submodule graph maps to stable node ids
- missing `.gitmodules` returns empty relationships, not failure
- selected peer changes request key
- static response can replace `GraphSimTap` output without component changes

### `treeTap.ts`

Purpose:

- Replace direct `WORKSPACE_FILES` use in `FileExplorer`.

Provides:

- `WORKSPACE_TREE`
- `WORKSPACE_TREE_VERSION`

Params:

- `SELECTED_PEER_ID`

Protocol:

- `tree.subscribe`
- `tree.refresh` via command helper

Tests:

- tree snapshot builds expected nested explorer structure
- `upsertEntry` adds/updates file
- `removeEntry` deletes file
- `moveEntry` renames/moves file
- ignored paths never appear
- reset replaces full tree
- `FileExplorer` no longer imports `WORKSPACE_FILES` in service mode

### `fileContentTap.ts`

Purpose:

- Service-backed parallel to current mock `src/lab/fileContentTap.ts`.
- Maintain per-editor-column file streams using destination context.

Provides:

- `FILE_CONTENT`
- `FILE_GIT_STATUS`
- `FILE_STREAM_STATUS`
- `FILE_LINE_INDEX`

Destination params:

- `ACTIVE_FILE`
- `FILE_REF`
- `FILE_WINDOW`

Home params:

- `SELECTED_PEER_ID`
- possibly `PEERS` until source keys are independent of peer display records

Protocol:

- `file.subscribe`
- `file.window.update`
- `file.unsubscribe`

File key:

```text
peerId + workspaceId + repoPath + path + ref + destContext.id
```

Rules:

- Empty `ACTIVE_FILE` returns empty content and idle stream status.
- `ACTIVE_FILE` retains existing `"repoPath::path"` shape until a richer file
  identity grip is introduced.
- `FILE_WINDOW` is per destination context. It starts with an initial overscan
  window and updates from editor scroll/viewport events.
- Deltas are applied through the TypeScript filedelta reassembler, never by ad
  hoc string patching.
- Decode bytes after hash-validated reassembly.
- Reset replaces the reassembler state.
- Stream cleanup must call `file.unsubscribe` on abort/detach.

Tests:

- initial snapshot maps to `FILE_CONTENT`
- grow/shrink window update calls `file.window.update`
- reset replaces content
- visible bytes unchanged maps metadata-only delta without content churn
- malformed hash closes stream and exposes `FILE_STREAM_STATUS.error`
- two editor columns viewing the same file have independent stream/window ids
- selected peer/ref/file changes unsubscribe old stream and subscribe new stream
- service tap consumes generated filedelta fixtures

### `sessionsTap.ts`

Purpose:

- Replace mock `SESSIONS` data and command creation side effects.

Provides:

- `SESSIONS`

Params:

- `SELECTED_PEER_ID`
- `SESSION_FILTERS` only if filters move server-side; otherwise filters remain
  local in `SessionsView`

Protocol:

- `sessions.subscribe`
- `cmd.run`, `cmd.interrupt`, `sessions.hide`, `sessions.purge` are command
  helpers called by UI actions, not fetcher-side effects

Tests:

- session snapshot maps to current `CommandSession`
- session target status updates
- hidden state update preserved
- reconnect rebuilds from canonical snapshot
- command helper sends repo targets and argv correctly

### `sessionOutputTap.ts`

Purpose:

- Service-backed parallel to current mock `src/lab/sessionOutputTap.ts`.

Provides:

- `SESSION_OUTPUT`
- `SESSION_DIAGNOSTICS`
- `SESSION_OUTPUT_STATUS`

Params:

- `SELECTED_SESSION`
- `SELECTED_TARGET`

Protocol:

- `session.output.subscribe`

Rules:

- Output remains raw text/bytes decoded by the browser renderer.
- Diagnostics parsing can reuse `parseDiagnostics()` from the mock tap or move
  it into a shared utility.
- Empty selection returns empty output and `none` diagnostics.

Tests:

- initial stored output maps to grip
- live output append updates output
- target switch unsubscribes old target and subscribes new target
- ANSI output remains available; diagnostics parser strips ANSI only for parsing
- stream error maps to `SESSION_OUTPUT_STATUS`

### `chatMessagesTap.ts`

Purpose:

- Replace mock `CHAT_MESSAGES` while leaving `CHAT_DRAFT` and `CHAT_PENDING`
  local.

Provides:

- `CHAT_MESSAGES`
- `CHAT_STREAM_STATUS`

Params:

- selected hub/workspace if needed

Protocol:

- `chat.subscribe`
- `chat.post` is a command helper used by composer submit

Tests:

- ordered snapshot maps messages
- delta appends one message
- malformed links rejected by validator
- optimistic pending behavior does not duplicate committed message
- reconnect resubscribes and preserves order

### `probeTap.ts`

Purpose:

- Support onboarding "Check" flow without embedding network probe logic in the
  component.

Provides:

- `ONBOARDING_FORM` or a narrower `ONBOARDING_PROBE_RESULT` grip if added

Params:

- `ONBOARDING_FORM`

Protocol:

- `peer.probe`

Rules:

- Consider adding `ONBOARDING_PROBE_RESULT` instead of letting a service tap
  overwrite the entire form. That keeps user-entered fields locally owned.

Tests:

- idle when ssh/location missing
- successful probe maps OS/shells/online
- failed probe maps stable error state
- stale result from old form value is ignored

## Component Integration Work

### File Explorer

Current issue:

- `FileExplorer` imports `WORKSPACE_FILES` directly.

Plan:

- Add `WORKSPACE_TREE` grip.
- Convert `FileExplorer` to read `WORKSPACE_TREE`.
- Mock bundle provides `WORKSPACE_TREE` from `WORKSPACE_FILES`.
- Service bundle provides `WORKSPACE_TREE` from `treeTap.ts`.

Tests:

- mock explorer renders same rows as before
- service fixture tree renders same nested rows
- no direct `WORKSPACE_FILES` import remains in `FileExplorer`

### Workspace Status

Plan:

- Convert status components to read `WORKSPACE_STATUS` instead of fake data
  directly, if they do not already.
- Mock bundle provides `WORKSPACE_STATUS` from fake data.
- Service bundle provides `WORKSPACE_STATUS` from `workspaceStatusTap.ts`.

Tests:

- mock and service fixtures render same repo count/status badges

### Workspace Graph

Plan:

- Keep `GraphSimTap` in mock mode.
- Service mode uses `depsGraphTap.ts`.
- If animation/layout still needs derived render nodes, split graph logic:
  service tap provides graph data; a small local derived tap computes
  `GRAPH_NODES`.

Tests:

- graph data maps stable node ids
- selecting graph mode does not start service graph requests if the view is not
  mounted or no peer is selected

### File Viewer

Plan:

- Keep child-context params.
- Add per-column `FILE_WINDOW` atom tap in `FilePane`, initialized to the first
  visible window plus overscan.
- On scroll, debounce and update `FILE_WINDOW_TAP`.
- Service `fileContentTap.ts` uses `FILE_WINDOW` to call `file.window.update`.
- Mock file tap may ignore `FILE_WINDOW`.

Tests:

- scroll changes per-column `FILE_WINDOW`
- two columns retain independent windows
- focus-line can force a one-time window request around the focused line

### Sessions

Plan:

- Keep view-local filters/draft/dialog state as atom taps.
- Replace session list and output sources in service mode.
- Move command/run side effects from direct mock mutations to command helper
  functions exposed by `serviceClient`.
- Mock mode keeps current mutation behavior.

Tests:

- mock run button still creates fake session
- service run button sends `cmd.run`
- selected session survives list refresh when id still exists

### Chat

Plan:

- Keep draft/pending local.
- Service mode sends `chat.post` through service client.
- Committed messages come from `chatMessagesTap.ts`.
- Mock mode keeps local append behavior.

Tests:

- mock composer still appends locally
- service composer posts and waits for hub message
- links still drive existing grip updates

## Test Plan

### Unit Tests

Add focused tests for:

- request key builders
- protocol validators
- service-to-UI mappers
- filedelta fixture consumption by service file tap
- diagnostics parser shared utility
- tree reducer
- sessions reducer
- chat reducer

### Tap Tests

Use a fake `ServiceClient` with deterministic responses/streams.

Each service tap test should cover:

- `requestKeyOf` returns `undefined` when required params are missing
- `fetcher` sends the expected method/payload
- abort signal unsubscribes/cancels
- `mapResult` writes the expected output grips
- malformed payload maps error/status rather than throwing into React

### Component Smoke Tests

At minimum:

- `FileExplorer` with mock tree fixture
- `FileExplorer` with service tree fixture
- `FileViewerView` two columns with independent service file streams
- `SessionsView` with service session fixture
- `ChatView` with service messages fixture

### End-To-End Manual Checks

Mock mode:

- `VITE_GL_DATA=mock npm run dev`
- open files, diff, sessions, chat; behavior matches current app

Service mode:

- start local client
- `VITE_GL_DATA=service npm run dev`
- workspace status loads
- explorer tree loads
- open file, scroll, edit file on disk, observe content update
- run command, observe session/output
- restart service, browser reconnects and resubscribes

### Build Commands

- `npm run build`
- `npm run lint`
- `npm test`
- service package tests from `dev-docs/GLServicesRollBuildPlan.md`
- filedelta dependency tests:
  `PYTHONPATH=services/filedelta/src python3 -m unittest discover -s services/filedelta/tests`
- TypeScript filedelta tests:
  `npm test --prefix services/filedelta-ts`

## Roll-Build Integration Phases

### UI Phase A: tap-bundle split

Deliverables:

- `registerLabMockTaps()`
- `registerLabServiceTaps()` stub
- `VITE_GL_DATA` bootstrap switch
- no behavior change in mock mode

Exit:

- mock app behaves as before
- build/lint/test pass

### UI Phase B: service client core

Deliverables:

- `ServiceClient`
- protocol envelope validators
- stream store
- fake service client test harness

Exit:

- request/subscribe/reconnect unit tests pass

### UI Phase C: tree/workspace/deps taps

Deliverables:

- `workspaceStatusTap.ts`
- `depsGraphTap.ts`
- `treeTap.ts`
- `FileExplorer` reads `WORKSPACE_TREE`

Exit:

- mock and service fixture modes both render explorer/status/graph

### UI Phase D: file content tap

Deliverables:

- service `fileContentTap.ts`
- `FILE_WINDOW` per-column grip
- filedelta reassembler integration
- scroll/window update path

Exit:

- generated filedelta fixtures pass through the tap
- two editor columns are independent
- manual local file edit updates content

### UI Phase E: sessions taps

Deliverables:

- `sessionsTap.ts`
- `sessionOutputTap.ts`
- command helper bridge

Exit:

- sessions list/output no longer depends on mock data in service mode
- mock sessions still work in mock mode

### UI Phase F: chat/probe taps

Deliverables:

- `chatMessagesTap.ts`
- `probeTap.ts`
- service command helpers for `chat.post` and `peer.probe`

Exit:

- chat and onboarding use service data in service mode
- mock mode still works

## Open Decisions Before Coding

- Whether service taps update outputs only via `mapResult`, or whether stream
  events may push directly into GRIP through a controlled service-client bridge.
- Exact test harness for tap execution: reuse existing GRIP runtime in tests or
  add small tap-level fake contexts.
- Whether to add new domain grips in `src/lab/grips.service.ts` or keep all grips
  in `src/lab/grips.ts`.
- Whether `probeTap.ts` should write `ONBOARDING_FORM` or a narrower
  `ONBOARDING_PROBE_RESULT`.
- Whether graph service output should directly provide `GRAPH_NODES` or a new
  `DEPS_GRAPH` grip with a derived render-node tap.

## Readiness

This plan should be completed before implementing service Phase 8 and before
rewiring any current component away from mock data. It is also useful earlier:
Phase 5 file-window integration needs the service `fileContentTap.ts` shape and
the `FILE_WINDOW` grip decision.

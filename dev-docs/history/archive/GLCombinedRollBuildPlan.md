# GLCombinedRollBuildPlan

Combined roll-build sequence for implementing the backend services in
`dev-docs/GLServicesRollBuildPlan.md` and the frontend service tap integration
in `dev-docs/GLIntegrationPlan.md`.

This document does not replace those plans. It is the execution crosswalk that
keeps backend protocol work and UI tap work aligned so the project does not grow
two partial service clients or land backend features without a usable GRIP path.

## Roll-Build Rule

Each combined step is still built, verified, committed, and tagged as a small
slice. Do not implement the whole combined plan in one branch-sized change.

Before starting:

- worktree is clean
- delta file protocol is at least `delta-build/phase-8-filedelta-hardening`
- service start tag is chosen, e.g. `serv-grip-build/start`
- frontend mock mode remains available and green
- `createAsyncStreamMultiTap` availability is decided for this checkout

## Preflight: Stream Tap Primitive

Goal:

- Decide how long-lived websocket streams are represented in GRIP taps before
  building service-backed taps.

Inputs:

- `grip-core` spike: `createAsyncStreamMultiTap`
- `GLIntegrationPlan.md` service tap pattern

Deliverables:

- Merge and publish `@owebeeone/grip-core` with `createAsyncStreamMultiTap`, or
  pin a local workspace dependency during the roll-build.
- Bump `@owebeeone/grip-core` in `@owebeeone/grip-react`, then release
  `@owebeeone/grip-react`, or pin both packages locally.
- Bump `grip-lab` to the released or locally pinned `@owebeeone/grip-react`.
- Update parent workspace submodule pins when local checkout references matter.
- Confirm `grip-lab` can import the keyed context helpers from
  `@owebeeone/grip-react`: `useKeyedChildContext` and
  `useKeyedMatchingContext`.
- Update `GLIntegrationPlan.md` so it describes the one-shot vs stream tap
  split, not a blanket `createAsyncMultiTap` rule for every non-trivial tap.
- Mark the stream update mechanism open decision in `GLIntegrationPlan.md` as
  resolved once the final stream tap API is selected.

Verification:

- `grip-core` stream tap tests pass.
- `grip-react` exports the stream tap API.
- `grip-lab` build can import the chosen stream tap API through
  `@owebeeone/grip-react`.

Exit:

- service taps have a supported primitive for subscribe/update/unsubscribe
  lifecycles.
- `import { createAsyncStreamMultiTap } from "@owebeeone/grip-react"` works in
  `grip-lab`.
- keyed context helper imports from `@owebeeone/grip-react` work in
  `grip-lab`.

## Keyed Context Rules

Use the new get-or-create context APIs for repeated panes, columns, and
service-mode context subgraphs. Do not create service-mode child contexts with
component-local `useMemo(() => parent.createChild(), ...)` or equivalent ad hoc
context construction.

Rules:

- Use `useKeyedChildContext(key, ...)` for simple isolated per-pane state, such
  as a selected file, selected session, or per-pane input atom.
- Use `useKeyedMatchingContext(key, { init })` when a pane installs local
  matcher bindings, such as service-vs-mock provider selection or peer/file
  stream provider selection.
- Keys are stable UI identity strings supplied by the caller, for example
  `files:left`, `files:right`, `session:<sessionId>`, or `diff:left`.
- Init lambdas may create the context subgraph and install matcher bindings for
  that keyed context. They must not depend on render-varying values; per-pane
  runtime values belong in atom taps inside the keyed context.
- Prefer stable named init functions declared outside the rendering component,
  or otherwise memoized, when passing `init` to `useKeyedChildContext(...)` or
  `useKeyedMatchingContext(...)`. The core get-or-create API prevents duplicate
  initialization for an existing key, but stable init functions keep React
  dependencies quiet and make context setup auditable.
- Keep mock-mode context construction stable until the service-mode replacement
  for that surface is in place; do not break the current functional mock while
  introducing keyed service contexts.
- The same pattern must remain portable to `grip-py`: service/demo Python
  contexts should use `get_or_create_child_context(...)` and
  `get_or_create_matching_context(...)` when mirroring repeated-pane behavior.

Verification:

- source scan for service-mode UI code finds no ad hoc `createChild()` wrapped
  in `useMemo` for repeated panes.
- two same-type panes using the same parent but different keys do not share
  local atom state or stream lifecycle.
- rerendering a pane with the same key does not reinstall matcher bindings or
  restart streams unless its request grips changed.

## Tap Primitive Rules

Use stream taps for long-lived subscriptions and one-shot async taps for bounded
request/response calls.

| Tap | Primitive | Reason |
| --- | --- | --- |
| `workspaceStatusTap.ts` | `createAsyncStreamMultiTap` | `workspace.status.subscribe` stream |
| `treeTap.ts` | `createAsyncStreamMultiTap` | `tree.subscribe` stream |
| `fileContentTap.ts` | `createAsyncStreamMultiTap` | `file.subscribe` plus window updates |
| `diffContentTap.ts` | `createAsyncStreamMultiTap` | `diff.subscribe` plus `diff.window.update` |
| `sessionsTap.ts` | `createAsyncStreamMultiTap` | `sessions.subscribe` stream |
| `sessionOutputTap.ts` | `createAsyncStreamMultiTap` | `session.output.subscribe` stream |
| `terminalTap.ts` | `createAsyncStreamMultiTap` | PTY output stream plus input helpers |
| `chatMessagesTap.ts` | `createAsyncStreamMultiTap` | `chat.subscribe` stream |
| `peersTap.ts` | `createAsyncStreamMultiTap` | presence stream |
| `depsGraphTap.ts` | `createAsyncMultiTap` | `deps.get` one-shot |
| `probeTap.ts` | `createAsyncMultiTap` | `peer.probe` one-shot |
| `serviceStateTap.ts` | atom tap or one-shot async tap | connection lifecycle state, not content data |

`ServiceClient.subscribe()` should expose an async event stream that can be
consumed by `createAsyncStreamMultiTap`. One-shot taps should use the normal
request/response path. `diff.get` is a one-shot `ServiceClient.request()` path,
not a stream tap.

## Combined Step 0: Protocol Skeleton + UI Tap-Bundle Split

Backend scope:

- Services Phase 0: service package skeleton and protocol models.

Frontend scope:

- UI Phase A: tap-bundle split.

Deliverables:

- `services/griplab_service` package skeleton.
- Python protocol envelope and stream event models.
- TypeScript protocol interfaces/validators in the chosen frontend location.
- service-owned grips split into `grips.service.ts`; UI atoms stay in
  `grips.ts`.
- `registerLabMockTaps()`.
- `registerLabServiceTaps()` stub.
- `VITE_GL_DATA=mock|service` bootstrap switch.
- identify the repeated UI panes that will require keyed contexts and document
  their stable keys in the integration checklist.
- `vitest` or the chosen unit-test harness for `src/lab/serviceClient/**`.
- `test:unit` script if `npm test` remains reserved for existing project checks.
- Mock mode remains the default.

Verification:

- protocol encode/decode tests pass in Python.
- TypeScript protocol validator tests pass.
- service client/tap unit-test harness can run with a fake transport.
- `npm run build`
- `npm run lint`
- `npm test`
- mock app behavior unchanged.

Exit:

- app can start in mock mode exactly as before.
- service mode can register local UI atom taps plus no-op service placeholders
  without duplicate providers for the same grips.

## Combined Step 1: Local Service Core + Browser Service Client Core

Backend scope:

- Services Phase 1: single-machine local service.

Frontend scope:

- UI Phase B: `ServiceClient` core and stream store.

Deliverables:

- `griplab client --config <fixture-config>` starts/stops cleanly.
- local config loader.
- health/probe endpoint.
- single-instance takeover skeleton.
- browser `ServiceClient`.
- `serviceStateTap.ts` for `SERVICE_CONNECTION` with disconnected, connected,
  reconnecting, and error states.
- stream id allocation.
- request id allocation.
- protocol envelope validation.
- `VITE_GL_SERVICE_URL`, defaulting to the local client websocket URL from the
  generated local config when not explicitly set.
- fake service client test harness.

Verification:

- client startup/shutdown smoke test.
- probe returns OS/shell/git/watchdog capability fields.
- browser client request/response unit tests.
- reconnect and unsubscribe behavior unit tests using fake transport.
- service state tap maps connection lifecycle events.
- local development recipe works: start `griplab client`, then run the app with
  `VITE_GL_DATA=service`.

Exit:

- frontend has one shared service client module.
- no tap opens its own websocket.

## Combined Step 2: Workspace Status + Dependency Graph

Backend scope:

- Services Phase 2: workspace discovery and git status stream.
- Services Phase 3: dependency graph scan.

Frontend scope:

- first half of UI Phase C: workspace/deps taps.

Deliverables:

- repo discovery from declared root.
- submodule enumeration one level deep.
- git status snapshot/delta/reset.
- `workspace.status.subscribe`.
- `workspace.status.refresh`.
- `deps.get`.
- service `workspaceStatusTap.ts`.
- service `depsGraphTap.ts`.
- mock providers for `WORKSPACE_STATUS` and any new graph data grips.
- `WorkspaceStatusView` reads workspace grips, not `fakeData`.
- `WorkspaceGraphView` and graph helpers read graph grips, not static
  dependency edge data.

Verification:

- temp git repo/submodule tests.
- missing/uninitialized submodule tests.
- workspace status tap maps snapshots/deltas.
- deps tap maps root/submodule graph.
- mock and service fixture modes render workspace status and graph.
- source scan confirms workspace status and graph views no longer import
  `fakeData` for these data paths.

Exit:

- Workspace status and graph views can run from service fixtures.
- Mock graph/status behavior remains available.

## Combined Step 2A: Workspace Status Delta Polling

Backend scope:

- Complete the live portion of Services Phase 2 after the initial websocket
  snapshot path is in place.

Frontend scope:

- Keep the existing service `workspaceStatusTap.ts` API, but verify it handles
  repeated stream events without resubscribing or losing the last good value.

Deliverables:

- per-`workspace.status.subscribe` polling task owned by the websocket
  connection.
- configurable poll interval, with a short test/dev default and a clear config
  field for local service use.
- initial `snapshot` event on subscribe.
- snapshot-on-change event when git status changes. Do not invent fine-grained
  repo deltas until the snapshot path proves too expensive.
- `workspace.status.refresh` request that forces an immediate rescan and emits
  a new snapshot to active stream subscribers.
- stable content hash or version key for the serialized workspace status so
  unchanged polls do not publish duplicate events.
- cancellation of polling tasks on websocket disconnect.
- protocol error for refresh requests when no workspace stream is active, or a
  documented no-op response if that is the selected v1 behavior.

Rules:

- `deps.get` remains request/response in this step; do not add
  `deps.subscribe` unless a UI workflow requires it.
- Polling is only for workspace git status. File tree changes belong to the
  watchdog tree step.
- Snapshot-on-change is acceptable for v1. Fine-grained deltas can be added
  later behind the same `workspace.status.subscribe` method.

Verification:

- websocket subscribe emits the initial workspace snapshot.
- modifying a tracked file emits exactly one new snapshot after the polling
  interval.
- adding an untracked file emits a new snapshot.
- repeated polls with no status change do not emit events.
- `workspace.status.refresh` emits a new snapshot immediately.
- closing the websocket cancels the polling task.
- frontend service workspace tap applies two successive stream events and leaves
  `WORKSPACE_REPOS` at the latest snapshot.
- mock workspace status remains unchanged.

Exit:

- Workspace status updates live in service mode without a page refresh.
- The implementation still uses one shared browser `ServiceClient`; taps do not
  create their own websocket connections.

## Combined Step 3: Watchdog Tree + Explorer Tap

Backend scope:

- Services Phase 4: watchdog tree stream.

Frontend scope:

- second half of UI Phase C: tree tap and explorer conversion.

Deliverables:

- watchdog adapter.
- ignore policy.
- tree snapshot/delta/reset.
- `tree.subscribe`, `tree.unsubscribe`, `tree.refresh`.
- `WORKSPACE_TREE` and `WORKSPACE_TREE_VERSION` grips.
- service `treeTap.ts`.
- mock `WORKSPACE_TREE` provider backed by existing fake data.
- `FileExplorer` reads grips, not fake data directly.

Verification:

- temp directory create/modify/delete/rename tests.
- ignored paths do not publish.
- overflow/mass-change emits reset.
- mock explorer renders same rows as before.
- service fixture tree renders expected rows.
- source scan confirms `FileExplorer` no longer imports mock file data.

Exit:

- File explorer can run from either mock tree tap or service tree tap.

## Combined Step 4: File Window Service + File Content Tap

Backend scope:

- Services Phase 5: file window stream integration.

Frontend scope:

- UI Phase D: service file content tap.

Deliverables:

- service source/window subscription registry.
- websocket mapping for `file.subscribe`, `file.window.update`,
  `file.unsubscribe`, snapshots, deltas, resets, and errors.
- browser service `fileContentTap.ts`.
- `services/filedelta-ts` import wrapped by a frontend module such as
  `src/lab/serviceClient/filedelta/index.ts`; package wiring is via `file:`
  dependency or an explicit path alias, not scattered relative imports.
- `FILE_WINDOW`, `FILE_WINDOW_TAP`, `FILE_STREAM_STATUS`, `FILE_LINE_INDEX`.
- per-column window tracking in file viewer uses
  `useKeyedMatchingContext(...)` or `useKeyedChildContext(...)` with stable
  pane keys instead of `useMemo(() => createChild())`.
- TypeScript filedelta reassembler integrated into the tap.

Rules:

- Keep existing mock `fileContentTap.ts`.
- Service file tap uses `createAsyncStreamMultiTap`.
- File stream request key includes destination context id when column-local
  window state must be independent.
- Do not include display-only `PEERS` in file stream request keys.
- Empty file selection returns idle/empty outputs.

Verification:

- backend service tests for start/reset/grow/shrink/window update routing.
- browser file tap consumes generated filedelta fixtures.
- malformed hash closes stream and exposes `FILE_STREAM_STATUS.error`.
- two editor columns viewing the same file maintain independent windows.
- rerendering either editor column with the same pane key does not recreate its
  context or resubscribe the file stream.
- scroll changes `FILE_WINDOW` and sends `file.window.update`.
- manual local file edit updates content.
- mock diff/file consumers are moved toward grip-fed file data where practical,
  without requiring cross-peer diff service behavior or structured diff hunks
  yet. Structured diff hunks are deferred to Step 10E-2.

Exit:

- Files view can show service-backed local text-window content.
- Mock file view still works in mock mode.

## Combined Step 5: Commands, Terminals, Sessions + Session Taps

Backend scope:

- Services Phase 6: command execution, terminals, session store.
- Services Phase 7: sessions query / grepsql.

Frontend scope:

- UI Phase E: sessions taps and command helper bridge.

Deliverables:

- session store layout.
- append-only events/output logs.
- Unix PTY execution.
- `cmd.run`, `cmd.interrupt`.
- `term.open`, `term.input`, `term.resize`, `term.close`.
- `sessions.subscribe`, `session.subscribe`, `session.output.subscribe`.
- `sessions.query`.
- service `sessionsTap.ts`.
- service `sessionOutputTap.ts`.
- service `terminalTap.ts` for interactive PTY output, input, resize, and close.
- session detail/terminal panes use keyed contexts for per-pane selected
  session, terminal size, input focus state, and output stream lifecycle.
- command helper bridge used by `SessionsView` in service mode.
- shared diagnostics parser utility.

Verification:

- command runs in repo root.
- interrupt works.
- interactive terminal opens, receives input, resizes, closes, and replays
  output.
- session list reconstructs after restart.
- sessions query by command/output/peer/repo/status.
- session taps map snapshots/deltas/output append.
- terminal tap opens, streams output, sends input, resizes, closes, and cleans up
  when listeners are gone.
- switching between two session panes does not leak terminal/session atom state
  across panes.
- mock session run behavior still works in mock mode.
- source scan confirms `SessionsView` no longer imports `fakeData` for service
  mode data paths.

Exit:

- Sessions view can use service-backed sessions and output.
- terminal v1 behavior is explicit and tested.

## Combined Step 6: Local Service App Integration Gate

Backend scope:

- Services Phase 8: local single-peer integration and GRIP tap replacement
  hardening.

Frontend scope:

- integration hardening across UI Phases A-E.

Deliverables:

- real-transport reconnect/resubscribe integration test for the Step 1
  `ServiceClient`.
- stream ref-counting integration checks across workspace, tree, file, and
  session streams.
- `registerLabServiceTaps()` complete for local single-peer scope.
- remaining component `fakeData` imports removed or guarded out of service mode
  for workspace, explorer, file viewer, sessions, and local status surfaces.
- `SERVICE_CONNECTION` rendered consistently from `serviceStateTap.ts`.
- service-mode manual script covering `griplab client` plus
  `VITE_GL_DATA=service npm run dev`.
- service-mode repeated panes use keyed contexts consistently for file,
  session, terminal, diff, and any peer-scoped pane state.
- render coalescing or burst-delta debounce only if profiling shows a real
  problem.

Verification:

- local app usable in `VITE_GL_DATA=service`.
- service restart reconnects and resubscribes.
- multiple editor columns do not corrupt each other.
- source scan confirms service-mode repeated panes use
  `useKeyedChildContext`/`useKeyedMatchingContext` rather than local
  `useMemo(createChild)` patterns.
- workspace, explorer, file viewer, and sessions no longer require mock data in
  service mode.
- source scan confirms core local service views have no unguarded `fakeData`
  imports.
- mock mode still passes.

Exit:

- local single-machine app is usable without mock data for core workspace,
  files, and sessions.
- Service-mode live diff is not expected yet. Mock diff remains the diff path
  until hub diff stream Step 10D-4 and browser integration Steps 10E-1/10E-2.

## Combined Step 7: Hub + Presence + Routing

Backend scope:

- Services Phase 9: hub service and peer registry.

Frontend scope:

- peers/presence service tap completion.

Deliverables:

- hub startup.
- peer registry.
- `peer.hello`.
- presence stream.
- stream relay.
- route validation.
- service `peersTap.ts`.
- hub route and peer fields added to `SERVICE_CONNECTION`.

Verification:

- two local clients register to hub.
- presence updates on disconnect/reconnect.
- stream relay preserves stream ids and errors.
- `PEERS` maps self/online/display fields correctly.

Exit:

- browser can view local service through hub route.

## Combined Step 8: Hub-Owned Collaborator Bootstrap + Health

Backend scope:

- Services Phase 10: SSH bootstrap and forwarding.
- `dev-docs/GLCollaboratorBootstrapPlan.md`.

Frontend scope:

- collaborator presence and health diagnostics.
- onboarding service integration remains a thin add-collaborator/config path;
  the hub owns actual remote bootstrap.

Deliverables:

- hub loads configured collaborators from the default config home.
- automatic SSH bootstrap worker owned by the hub.
- remote `~/.griplab` creation.
- griplab client payload copied to the remote machine on every bootstrap.
- remote `client.json` writer.
- Python/uv runtime check and install/provision path when missing.
- ephemeral remote client start/restart.
- live client registration and heartbeat.
- `peer.presence.subscribe` reports configured, offline, bootstrapping,
  starting, online, and error states.
- `peer.health.get` returns detailed diagnostics for one collaborator.
- SSH target parsing.
- persistent remote service install is out of scope for the first SSH slice.
- service `probeTap.ts`.
- `ONBOARDING_PROBE_RESULT` as the dedicated result grip. `ONBOARDING_FORM`
  remains user input state and is not overloaded with probe output.
- Collaborators page health/status button opens a diagnostics dialog backed by
  `peer.health.get`.

Rules:

- SSH reachability alone never marks a collaborator online. Online is based on a
  live registered client connection and heartbeat.
- Missing Python, missing uv, stale client payload, and missing remote config are
  bootstrap work items, not final presence states.
- Presence remains compact and stream-friendly. Detailed check output belongs in
  `peer.health.get`.
- The remote client is ephemeral by default. Do not add launchd/systemd/Windows
  service installation in this step.

Verification:

- local SSH fixture where available.
- hub bootstrap creates remote griplab area and config.
- re-bootstrap copies/replaces the client payload cleanly.
- missing runtime fixture exercises install/provision behavior where the harness
  can model it.
- remote client starts, registers, heartbeats, and becomes online.
- killing the remote client changes presence away from online.
- two collaborators on the same SSH address but different peer ids/workspaces
  remain distinct.
- `peer.health.get` exposes SSH, payload, config, runtime, process,
  registration, and heartbeat diagnostics.
- auth/update/version failure states.
- stale probe result ignored when form changes.
- onboarding mock behavior still works in mock mode.

Exit:

- adding a collaborator is enough for the hub to attempt automatic bootstrap.
- collaborators page can explain offline/error collaborators without requiring
  server log inspection.

## Combined Step 9: Chat Store + Chat Tap

Backend scope:

- Services Phase 11: chat store and links.

Frontend scope:

- UI Phase F chat portion.
- Service-mode chat remains a placeholder until this step because message ids
  and routing depend on the hub from Step 7.

Deliverables:

- `chat.post`.
- `chat.subscribe`.
- hub-assigned message ids.
- per-message JSON storage.
- link schema validation.
- service `chatMessagesTap.ts`.
- service composer helper.
- `ChatView` reads message, file-link, and command-link data from grips in
  service mode, not directly from `fakeData`.

Verification:

- lexicographic message order.
- malformed links rejected.
- index rebuild from files.
- chat links still apply GRIP state.
- mock composer still appends locally.
- service composer posts and receives committed hub message.
- source scan confirms `ChatView` no longer imports `fakeData` for service mode
  data paths.

Exit:

- Chat panel uses hub-backed messages and links in service mode.

## Combined Step 10A: Hub Relay Contract

Backend scope:

- First slice of Services Phase 12: generic hub request/stream relay.

Frontend scope:

- No UI view replacement yet. This step proves the transport contract that later
  cross-peer taps will use.

Deliverables:

- hub registry stores each peer's active websocket connection.
- caller can send a routed request with `targetPeerId`.
- hub forwards the request to the target peer and returns the target response to
  the caller.
- caller can open a routed subscription stream.
- hub maps caller stream ids to target stream ids and relays stream events.
- route validation and errors: unknown peer, offline peer, bad target response,
  target error, and target timeout.
- request/stream correlation stays internal to the hub; callers and targets do
  not share message ids or stream ids directly.

Rules:

- Do not add feature-specific routing branches for files, workspace, sessions,
  or commands in this step. The output is a reusable relay seam.
- Routed requests must preserve the original service method name as the target
  method unless the relay explicitly documents an envelope wrapper.
- Stream relay must preserve target event ordering per routed stream.

Verification:

- two local clients register to one hub.
- client A can route a request to client B and receive B's response.
- client A can route a subscription to client B and receive B's stream events.
- disconnecting B closes or errors A's routed streams.
- route errors are structured service errors, not dropped messages.

Exit:

- cross-peer features have one tested relay contract to build on.

## Combined Step 10B: Cross-Peer Workspace Status

Backend scope:

- Apply the hub relay to `workspace.status.subscribe`, `workspace.status.refresh`,
  and `deps.get`.

Frontend scope:

- Cross-peer workspace/dependency service tap hardening.

Deliverables:

- service workspace/deps taps include selected peer routing when connected
  through the hub.
- selected local peer can still use the direct local client path.
- `WorkspaceStatusView` and graph data show the selected peer's workspace.

Verification:

- two local clients with different fixture repos show different routed workspace
  status through the hub.
- dependency graph requests route to the selected peer.
- switching peers does not leak stale workspace/dependency data.

Exit:

- status and graph views can inspect a non-local peer through the hub.

## Combined Step 10C: Cross-Peer File Windows

Backend scope:

- Apply the hub relay to `file.subscribe`, `file.window.update`, and file stream
  events.

Frontend scope:

- Cross-peer file viewer service tap hardening.

Deliverables:

- routed file window subscription.
- routed window grow/shrink updates.
- routed file stream errors and resets.
- file viewer switches selected peers and receives that peer's file window.

Rules:

- File request keys include peer id, repo/ref/file identity, and destination
  context where needed.
- Stream relay must not coalesce or reorder file deltas.

Verification:

- two peers with the same repo identity can show different file content.
- local file edits on the target peer reach the caller as valid deltas/resets.
- switching selected peers closes the old stream and opens the new routed stream.

Exit:

- file viewer can inspect a non-local peer through the hub.

## Combined Step 10D-1: Diffstream Models And Codec

Backend scope:

- Start the standalone `services/diffstream` package for the pure synthetic diff
  payload model.

Frontend scope:

- None.

Deliverables:

- `services/diffstream/pyproject.toml`.
- `diffstream.model` with endpoint, ref, window, line, hunk, diagnostic, source
  state, and payload dataclasses.
- `diffstream.codec` JSON round-trip for
  `application/vnd.griplab.diff+json;version=1`.
- version/id conventions for `diffId`, payload `version`, and hunk ids.
- golden fixtures for empty/same diff and diagnostics in
  `services/diffstream/fixtures/`.
- `griplab_service` consumes `diffstream` through the same local editable/path
  dependency pattern used for `services/filedelta`.
- no imports from `griplab_service`, `aiohttp`, watchdog, git, or GRIP.

Verification:

- `uv run --with pytest --with-editable services/diffstream pytest services/diffstream/tests -q`
- JSON fixture round-trips preserve the exact protocol field names.
- import scan confirms `diffstream` is service-independent.

Exit:

- structured diff payloads can be generated, validated, serialized, and tested
  without the hub.

## Combined Step 10D-2: Diffstream Algorithm

Backend scope:

- Implement the pure text diff algorithm in `services/diffstream`.

Frontend scope:

- None.

Deliverables:

- `diffstream.algorithm` using Python stdlib `difflib.SequenceMatcher`.
- structured hunk conversion for same/add/delete/replace cases.
- context line behavior from `contextLines`.
- absolute one-based line numbers in hunks.
- same-path/window validation helpers.
- optional `unifiedText` generation when requested by `diff.get`.

Rules:

- Hunk line numbers are absolute one-based source-file display lines.
- Service mode is authoritative if mock LCS row boundaries differ.

Verification:

- same/add/delete/replace hunk conversion tests.
- context line and window-boundary tests.
- one-based line number tests.
- same-path and window-bound validation tests.

Exit:

- pure diff semantics are correct before any hub or websocket work.

## Combined Step 10D-3: DiffConnection With Fake Sources

Backend scope:

- Implement async diff orchestration in `services/diffstream` against abstract
  source streams.

Frontend scope:

- None.

Deliverables:

- `diffstream.connection.DiffConnection`.
- source-stream protocol for left/right snapshots, resets, and errors.
- ref-counted subscribers.
- sharing key fields: left endpoint, right endpoint, requested window,
  `contextLines`, and content type.
- recompute when either source changes.
- coalescing policy for concurrent left/right updates.
- diagnostics while either side is mid-reset or unavailable.
- unsubscribe closes source streams when the last subscriber leaves.

Rules:

- `diffstream.connection` may use `asyncio` but must not import hub/aiohttp code.
- Source updates are serialized; no diff snapshot is published from a partially
  applied source delta.

Verification:

- fake left/right source snapshots produce an ordered diff snapshot.
- update on either side recomputes.
- concurrent updates coalesce into ordered snapshots.
- source reset/error/binary/decode/missing outcomes produce diagnostics using
  codec types from Step 10D-1.
- ref-count tests prove source streams close after the last subscriber.

Exit:

- diff orchestration is testable without the hub.

## Combined Step 10D-4: Hub Diff Stream Integration

Backend scope:

- Wire `diffstream` into the hub-owned synthetic diff stream from
  `dev-docs/GLDiffStreamDesign.md`.

Frontend scope:

- None. Shared JSON fixtures on disk are allowed; all `src/lab` TypeScript
  types, validators, and taps are Step 10E-1.

Deliverables:

- `diff.subscribe`.
- `diff.window.update`.
- `diff.unsubscribe`.
- optional one-shot `diff.get` returning the same structured payload shape.
- hub adapter that turns routed `file.subscribe` streams into `diffstream`
  source streams.
- source peers serve both `working` and `head` refs for diff endpoints before
  stock UI defaults are considered service-ready; otherwise service-mode diff
  must temporarily default to `working`/`working`.
- hub resolves `peerId` through the registry; diff endpoints do not carry
  `workspaceId` in v1.
- structured hunk payload `application/vnd.griplab.diff+json;version=1`.
- diagnostics for missing file, binary file, decode failure, truncation,
  peer-offline, and unsupported ref.

Verification:

- reuse the existing dual local-client hub test harness rather than creating a
  separate ad hoc fixture.
- two local service peers through the hub produce a routed synthetic diff.
- fixture covers the stock `head` vs `working` pair, or documents the temporary
  `working`/`working` service fallback.
- editing either source file updates the synthetic diff stream.
- `diff.window.update`, `diff.unsubscribe`, and `diff.get` tests, including
  `includeUnifiedText: true`.
- peer disconnect produces a structured diagnostic or stream error.
- full service Python test suite remains green.

Exit:

- hub can publish canonical live structured diffs.

## Combined Step 10E-1: TypeScript Diff Types And Tap

Backend scope:

- None.

Frontend scope:

- Add TS protocol types/validators and the service diff stream tap.

Deliverables:

- service `diffContentTap.ts` using `createAsyncStreamMultiTap`.
- grips for diff hunks, diagnostics, stream status, and version.
- `DIFF_WINDOW` as the diff-specific window input grip.
- TypeScript diff payload types/parser in `src/lab/serviceClient/diff`.
- TS fixture tests consume Python golden fixtures from `services/diffstream`.
- register `createServiceDiffContentTap()` in `registerLabServiceTaps()`.
- put service-owned diff output grips in `grips.service.ts` or the established
  service grip module; keep UI atoms separate.
- tap request keys include selected file, left/right endpoints, `DIFF_WINDOW`,
  and destination context identity such as `diff:main`.
- debounced `diff.window.update` mirrors the `fileContentTap.ts` window update
  pattern.

Verification:

- TS parser accepts `diffstream` golden fixtures.
- `diffContentTap` maps snapshots to `DIFF_HUNKS`, `DIFF_DIAGNOSTICS`,
  `DIFF_STREAM_STATUS`, and `DIFF_VERSION`.
- `DIFF_WINDOW` participates in request keys and window update calls.
- service tap unregister/unsubscribe closes the diff stream.
- `npm run test:unit`
- `npm run build`

Exit:

- browser service code can consume synthetic diff streams without rendering
  changes.

## Combined Step 10E-2: Diff View Renderer Integration

Backend scope:

- No new backend protocol unless Step 10D-4 exposes a renderer-facing gap.

Frontend scope:

- Service and mock diff view integration.

Deliverables:

- `DiffViewerView` renders structured hunks from `diff.subscribe`.
- diff view uses a keyed context such as `diff:main`.
- `mockDiffContentTap.ts` or an equivalent mock provider emits the same
  structured hunk model at the tap boundary, converting from the existing
  TypeScript LCS helper if needed.
- existing state links still restore selected file, endpoints, and focus line.
- `DiffViewerView` no longer imports static file content for service mode.

Verification:

- diff view compares two peers/refs from a synthetic diff stream.
- diagnostics render without crashing the diff view.
- mock diff behavior remains available and renders through the same structured
  hunk path.
- source scan confirms service-mode diff path no longer depends on static file
  content.
- `npm run build`
- `VITE_GL_DATA=service npm run build`
- `npm run lint`
- `npm test`

Exit:

- service-mode diff works from the hub synthetic diff stream.

## Combined Step 10F: Remote Commands And Sessions

Backend scope:

- Apply the hub relay to `cmd.run`, `sessions.subscribe`, and
  `session.output.subscribe`.

Frontend scope:

- Cross-peer command/session service tap hardening.

Deliverables:

- remote `cmd.run`.
- remote session output subscription.
- command logs remain stored on the executor peer.
- caller can observe running and completed remote sessions.
- hub reconnect reconciles running command state.

Verification:

- remote command stores logs on executor.
- caller receives routed session id and output.
- reconnect preserves observable session state.

Exit:

- end-to-end two-peer collaborative workflow works for workspace, files, diff,
  and commands.

## Combined Step 11: Hardening And Release Prep

Backend scope:

- Services Phase 13: hardening and polish.

Frontend scope:

- integration hardening, browser/manual QA, docs.

Deliverables:

- path traversal tests.
- permission audit log.
- cap behavior tests.
- watchdog ignore tuning.
- Windows ConPTY implementation or explicit unsupported state.
- local operation docs.
- service-mode manual test script.
- mock-mode regression script.
- manual diff smoke script after Step 10E-2: hub plus two clients, open diff
  view, edit a source file, observe hunk update, and verify focus-line link.

Verification:

- focused security/path tests.
- long-running command smoke.
- large file/window cap behavior.
- `npm run build`
- `npm run lint`
- `npm test`
- service Python tests.
- filedelta Python and TypeScript tests.
- `uv run --with pytest --with-editable services/diffstream pytest services/diffstream/tests -q`
- hub synthetic diff integration tests from Step 10D-4.

Exit:

- ready for broader manual testing.

## Tagging Recommendation

Use one tag prefix for the combined service/UI rollout:

```text
serv-grip-build/start
serv-grip-build/step-0-protocol-ui-bundle
serv-grip-build/step-1-local-client-service-client
serv-grip-build/step-2-workspace-deps
serv-grip-build/step-3-tree-explorer
serv-grip-build/step-4-file-windows
serv-grip-build/step-5-sessions-terminals
serv-grip-build/step-6-local-service-app
serv-grip-build/step-7-hub-presence
serv-grip-build/step-8-ssh-onboarding
serv-grip-build/step-9-chat
serv-grip-build/step-10a-hub-relay
serv-grip-build/step-10b-cross-peer-workspace
serv-grip-build/step-10c-cross-peer-files
serv-grip-build/step-10d-1-diffstream-models
serv-grip-build/step-10d-2-diffstream-algorithm
serv-grip-build/step-10d-3-diffconnection-fakes
serv-grip-build/step-10d-4-hub-diff-stream
serv-grip-build/step-10e-1-ts-diff-tap
serv-grip-build/step-10e-2-diff-view
serv-grip-build/step-10f-remote-commands
serv-grip-build/step-11-hardening
```

## Guardrails

Pause the roll-build if:

- stream tap primitive behavior changes enough to invalidate service tap design
- backend protocol and frontend validators diverge
- a UI phase needs a second websocket client
- mock mode breaks
- filedelta fixture tests fail
- service file stream bugs cannot be separated from filedelta protocol bugs
- diffstream fixture tests fail
- hub diff stream bugs cannot be separated from pure diffstream semantics
- command/session persistence cannot reconstruct after restart
- hub reconnect loses authoritative state

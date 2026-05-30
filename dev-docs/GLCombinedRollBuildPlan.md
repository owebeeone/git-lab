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
request/response path.

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
  without requiring cross-peer diff service behavior yet.

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

## Combined Step 8: SSH Bootstrap + Onboarding Probe

Backend scope:

- Services Phase 10: SSH bootstrap and forwarding.

Frontend scope:

- `probeTap.ts` and onboarding service integration.

Deliverables:

- `peer.probe`.
- `peer.bootstrap`.
- SSH target parsing.
- remote client install/start/update path.
- service `probeTap.ts`.
- `ONBOARDING_PROBE_RESULT` as the dedicated result grip. `ONBOARDING_FORM`
  remains user input state and is not overloaded with probe output.

Verification:

- local SSH fixture where available.
- auth/update/version failure states.
- stale probe result ignored when form changes.
- onboarding mock behavior still works in mock mode.

Exit:

- collaborator can be checked and bootstrapped through service flow.

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

## Combined Step 10: Cross-Peer File, Diff, Workspace, Commands

Backend scope:

- Services Phase 12: cross-peer workspace, file, diff, command.

Frontend scope:

- diff view service integration.
- cross-peer service tap hardening.

Deliverables:

- cross-peer workspace status.
- cross-peer file window streams.
- client-derived diff from two `file.subscribe` streams.
- remote `cmd.run`.
- remote session output subscription.
- service-backed `DiffViewerView` data path.
- diff left/right sides use independent keyed contexts so file stream windows,
  peer/ref selections, decode status, and stream errors are isolated.
- `DiffViewerView` no longer imports static file content for service mode.

Rules:

- Diff view uses two independent file streams and the existing line diff logic
  only after both byte streams are hash-valid and decoded.
- Diff endpoint request keys include peer/ref/file identity and destination
  context where needed.

Verification:

- two peers with same repo identity show status differences.
- file viewer can switch peers.
- diff view compares two peers/refs.
- remote command stores logs on executor.
- hub reconnect reconciles running command state.

Exit:

- end-to-end two-peer collaborative workflow works.

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

Verification:

- focused security/path tests.
- long-running command smoke.
- large file/window cap behavior.
- `npm run build`
- `npm run lint`
- `npm test`
- service Python tests.
- filedelta Python and TypeScript tests.

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
serv-grip-build/step-10-cross-peer
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
- command/session persistence cannot reconstruct after restart
- hub reconnect loses authoritative state

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
- service start tag is chosen, e.g. `services-build/start`
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

- Either release/update `@owebeeone/grip-core` and `@owebeeone/grip-react`, or
  pin a local workspace dependency for the service tap roll-build.
- Update `GLIntegrationPlan.md` if the final stream tap API differs from the
  spike.

Verification:

- `grip-core` stream tap tests pass.
- grip-lab build can import the chosen stream tap API.

Exit:

- service taps have a supported primitive for subscribe/update/unsubscribe
  lifecycles.

## Combined Step 0: Protocol Skeleton + UI Tap-Bundle Split

Backend scope:

- Services Phase 0: service package skeleton and protocol models.

Frontend scope:

- UI Phase A: tap-bundle split.

Deliverables:

- `services/griplab_service` package skeleton.
- Python protocol envelope and stream event models.
- TypeScript protocol interfaces/validators in the chosen frontend location.
- `registerLabMockTaps()`.
- `registerLabServiceTaps()` stub.
- `VITE_GL_DATA=mock|service` bootstrap switch.
- Mock mode remains the default.

Verification:

- protocol encode/decode tests pass in Python.
- TypeScript protocol validator tests pass.
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
- stream id allocation.
- request id allocation.
- protocol envelope validation.
- fake service client test harness.

Verification:

- client startup/shutdown smoke test.
- probe returns OS/shell/git/watchdog capability fields.
- browser client request/response unit tests.
- reconnect and unsubscribe behavior unit tests using fake transport.

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

Verification:

- temp git repo/submodule tests.
- missing/uninitialized submodule tests.
- workspace status tap maps snapshots/deltas.
- deps tap maps root/submodule graph.
- mock and service fixture modes render workspace status and graph.

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
- `FILE_WINDOW`, `FILE_WINDOW_TAP`, `FILE_STREAM_STATUS`, `FILE_LINE_INDEX`.
- per-column window tracking in file viewer.
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
- scroll changes `FILE_WINDOW` and sends `file.window.update`.
- manual local file edit updates content.

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
- mock session run behavior still works in mock mode.

Exit:

- Sessions view can use service-backed sessions and output.
- terminal v1 behavior is explicit and tested.

## Combined Step 6: Full Browser Service Client + Local App Without Mocks

Backend scope:

- Services Phase 8: browser service client and GRIP tap replacement.

Frontend scope:

- integration hardening across UI Phases A-E.

Deliverables:

- one browser service client owns all websocket mechanics.
- stream ref-counting.
- reconnect/resubscribe.
- snapshot/delta/reset handling across workspace, tree, file, sessions.
- service tap registration bundle complete for local single-peer app.
- render coalescing if needed.

Verification:

- local app usable in `VITE_GL_DATA=service`.
- service restart reconnects and resubscribes.
- multiple editor columns do not corrupt each other.
- workspace, explorer, file viewer, and sessions no longer require mock data in
  service mode.
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
- connection state surfaced through `SERVICE_CONNECTION`.

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
- `ONBOARDING_PROBE_RESULT` or documented decision to write
  `ONBOARDING_FORM`.

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

Deliverables:

- `chat.post`.
- `chat.subscribe`.
- hub-assigned message ids.
- per-message JSON storage.
- link schema validation.
- service `chatMessagesTap.ts`.
- service composer helper.

Verification:

- lexicographic message order.
- malformed links rejected.
- index rebuild from files.
- chat links still apply GRIP state.
- mock composer still appends locally.
- service composer posts and receives committed hub message.

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
services-build/start
services-build/step-0-protocol-ui-bundle
services-build/step-1-local-client-service-client
services-build/step-2-workspace-deps
services-build/step-3-tree-explorer
services-build/step-4-file-windows
services-build/step-5-sessions-terminals
services-build/step-6-local-service-app
services-build/step-7-hub-presence
services-build/step-8-ssh-onboarding
services-build/step-9-chat
services-build/step-10-cross-peer
services-build/step-11-hardening
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

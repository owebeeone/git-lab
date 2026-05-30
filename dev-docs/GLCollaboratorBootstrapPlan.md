# GLCollaboratorBootstrapPlan

Roll-build plan for hub-owned collaborator bootstrap, presence, and health
diagnostics.

This plan replaces the earlier idea that adding a collaborator only records a
static peer entry and leaves startup to the user. In v1, the hub owns the
automatic path from configured collaborator to running remote client.

## Goals

- Reading collaborator records from the default config home is enough to make
  the hub attempt to bring those collaborators online.
- Presence is small and live: it reports whether a collaborator is configured,
  bootstrapping, starting, online, offline, or in error.
- Health diagnostics are separate from presence and pulled on demand by the UI.
- The hub copies the current griplab client payload to the remote machine every
  time it bootstraps, so the remote client is kept in sync with the hub build.
- V1 verifies required collaborator machine tools and reports missing tools in
  health diagnostics. Runtime provisioning is deferred.
- After the initial shell fingerprint, remote setup should depend on Python
  only. Do not assume bash, tar, uv, or platform package managers are present.
- The remote client is ephemeral by default. Persistent service installation is
  deferred until there is a concrete need.
- The local SSH test harness is used for automated coverage before real remote
  machines are treated as reliable.

## Non-Goals

- Cross-platform service managers.
- Windows SSH bootstrap.
- Long-lived daemon installation.
- User/account provisioning beyond the provided SSH address and key.
- General package publishing for the SSH harness.

## Collaborator State Model

Presence states:

| State | Meaning |
| --- | --- |
| `configured` | The hub has a collaborator record but has not probed yet. |
| `offline` | SSH is unreachable or authentication failed. |
| `bootstrapping` | The hub is running preflight diagnostics, copying payload, writing config, or establishing SSH forwards. |
| `starting` | The hub issued the remote client start command and is waiting for registration. |
| `online` | The remote client has connected to the hub and is heartbeating. |
| `error` | Bootstrap/start failed after SSH was reachable. Details live in health. |

Rules:

- SSH reachability alone never means `online`.
- Missing config and stale client payload are not
  steady states. They are bootstrap work items.
- Missing required runtime tools are v1 `error` health states with install
  guidance, not automatic provisioning tasks.
- The hub may retry `offline`, `error`, and stale `online` peers using bounded
  backoff with jitter.
- The collaborator record remains the configuration source of truth. Live
  client registration is the online source of truth.
- `online` is retained as a backward-compatible boolean and is derived from
  `status === "online"`.
- Hub presence merges configured collaborators with live registered clients. A
  collaborator can appear before it has ever connected.
- Presence includes the hub/local self peer plus configured collaborators. Self
  is `online` when the hub has an active registered connection for `selfPeerId`.
  In local-client-only mode without a hub, self may be reported as `online` for
  that direct endpoint, but collaborator bootstrap presence is hub-authoritative.

Historical service design docs used older names such as `unknown`,
`forwarding`, `connecting`, `degraded`, and `versionMismatch`. For this active
plan, use the hub-owned states above:

| Historical state | Active v1 state |
| --- | --- |
| `unknown` | `configured` |
| `forwarding` | `bootstrapping` |
| `connecting` | `starting` |
| `degraded` | `error` with health diagnostics |
| `versionMismatch` | `error` or `bootstrapping`, depending on whether payload refresh is in progress |

## Protocol Surface

### `peer.presence.subscribe`

Presence stream. Payload stays compact enough for always-on UI cards.
V1 events are snapshot-only:

```ts
interface PeerPresenceSnapshot {
  peers: PeerPresence[];
}
```

```ts
interface PeerPresence {
  id: string;
  name: string;
  isSelf: boolean;
  online: boolean;
  status: "configured" | "offline" | "bootstrapping" | "starting" | "online" | "error";
  summary?: string;
  lastSeenAt?: number;
  sshAddress?: string;
  location?: string;
}
```

TypeScript `Peer` should be extended to include `status?: PeerPresence["status"]`
and `summary?: string`, while preserving existing `online` consumers during the
migration.

### `peer.health.get`

On-demand diagnostics for one collaborator.

Request:

```ts
interface PeerHealthGetRequest {
  peerId: string;
}
```

Response:

```ts
interface PeerHealth {
  peerId: string;
  status: PeerPresence["status"];
  updatedAt: number;
  checks: PeerHealthCheck[];
  logTail: string[];
}

interface PeerHealthCheck {
  id:
    | "ssh"
    | "ssh_tunnel"
    | "remote_home"
    | "client_payload"
    | "config"
    | "runtime"
    | "process"
    | "registration"
    | "heartbeat";
  status: "pending" | "running" | "ok" | "warn" | "error";
  message: string;
  updatedAt?: number;
}
```

Health log tails are bounded. V1 returns at most 200 lines and 64 KiB total,
with obvious secrets redacted before returning to the browser.

### Future Optional Endpoints

- `peer.bootstrap.restart` for manual retry.
- `peer.health.subscribe` if the health dialog needs live progress.

Do not add these until the request/response health dialog proves insufficient.

## Remote Layout

Default remote paths are relative to the collaborator user home:

- `~/.griplab/client.json`
- `~/.griplab/client/` for copied client payload
- `~/.griplab/logs/` for remote client output
- secure temporary directory for unpacking before atomic replacement

The hub should not require the collaborator workspace to be inside the griplab
client payload. The collaborator `location` points at the project workspace to
serve.

## Config Source Of Truth

The hub reads collaborator records from its active config root. The default
config root is `~/.griplab`, unless overridden by the explicit
`griplab hub --config <path>` flow or `GRIPLAB_HOME`.

Existing files:

```text
~/.griplab/collaborators.json   durable collaborator records; hub source of truth
~/.griplab/hub.json             hub service config; peers[] may be synced cache
~/.griplab/client.json          local client config
```

The hub reads `collaborators.json` directly. `hub.json` and `client.json`
`peers[]` entries may be synchronized by startup/helper tooling, but they are
not the authoritative collaborator list for hub bootstrap.

V1 collaborator records live in the same schema used by the add-collaborator
helper (`scripts/add_collaborator.py`):

```ts
interface CollaboratorRecord {
  peerId: string;
  name: string;
  sshAddress: string;
  location: string;
  identityFile?: string;
  knownHostsFile?: string;
  addedAt?: number;
  probe?: Record<string, unknown>;
}
```

Rules:

- `peerId` is the primary identifier for presence, health, and registration.
- `(peerId, sshAddress, location)` must be unique. Two collaborators may share
  an SSH address if they have distinct `peerId` and workspace `location`.
- Self peer identity comes from the hub/client config, not from collaborator
  records.
- Adding or removing a collaborator updates config and triggers hub reconcile.
- UI add/remove must not only update the in-memory `PEERS` grip; service mode
  writes through to the hub/config path.
- `identityFile` and `knownHostsFile` are host-local config paths. They are
  allowed in `~/.griplab` config, but must not be committed to repo files.
- The optional `probe` snapshot is historical/helper output only. It must not
  drive online presence after hub bootstrap exists.
- `scripts/start_griplab.py` currently syncs collaborators into generated
  service configs. Hub bootstrap should share the same collaborator load/upsert
  logic rather than reimplementing divergent JSON behavior.

## Network Path V1

V1 uses one maintained SSH session with both reverse and local forwards. The
first system must not require public or externally reachable ports.

The hub opens and maintains an SSH session to the collaborator with:

- `-R`: remote loopback port on the collaborator forwards back to the hub's
  local websocket listener. The remote griplab client uses this to register and
  heartbeat back to the hub.
- `-L`: hub-local loopback port forwards to the remote griplab client's local
  service listener. The hub uses this to reach the collaborator's service
  protocol for routed operations such as file streams, command execution,
  terminals, sessions, and health/debug calls when they are served by the remote
  client.

The remote `client.json` points its hub connection at the `-R` loopback forward,
not at a public hub address. The hub stores the `-L` endpoint in local tunnel
state for routing.

Example shape:

```json
{
  "hub": {
    "url": "ws://127.0.0.1:<remote-forward-port>",
    "connectionMode": "sshReverseForward"
  },
  "listen": {
    "host": "127.0.0.1",
    "port": "<remote-client-port>"
  }
}
```

Rules:

- Bootstrap health should include a clear `registration` failure when the remote
  client starts but cannot connect through the forwarded port.
- Do not mark online from the SSH session or process start. Online requires
  websocket registration plus heartbeat.
- The SSH tunnel session is part of the bootstrap worker's lifecycle. If either
  required forward dies, the hub marks the collaborator stale/offline and
  retries according to the bounded retry policy.
- The remote `-R` port is allocated by the hub from a configured safe range. V1
  default range: `43140-43239` on the collaborator loopback interface. The hub
  probes for an available port before writing config.
- The hub-local `-L` port is allocated by the hub from a configured safe range.
  V1 default range: `44140-44239` on the hub loopback interface.
- The remote griplab client listens on remote loopback. V1 default remote client
  service port is `3141` unless the generated `client.json` assigns a different
  value.
- The hub writes selected tunnel metadata into `~/.griplab/forward.json` and
  writes the remote `-R` hub URL plus remote client listen port into
  `~/.griplab/client.json` before starting the client.
- The SSH command shape is equivalent to
  `ssh -N -R 127.0.0.1:<remoteHubPort>:127.0.0.1:<hubWsPort> -L 127.0.0.1:<localPeerPort>:127.0.0.1:<remoteClientPort> <sshAddress>`.
- No public hub listener is required for collaborator bootstrap v1.

## Tunnel Registry

The hub owns a tunnel registry keyed by collaborator `peerId`. Every configured
collaborator that is bootstrapping or online has a distinct hub-local forwarded
listening port.

```ts
interface PeerTunnel {
  peerId: string;
  sshAddress: string;
  remoteHubPort: number;
  localPeerPort: number;
  remoteClientPort: number;
  hubWsPort: number;
  status: "starting" | "ready" | "error";
}
```

Rules:

- `localPeerPort` is unique per collaborator on the hub host.
- `remoteClientPort` may be reused across collaborators because it is bound on
  each collaborator's own loopback interface.
- Hub routing uses `localPeerPort` as the collaborator service endpoint.
- Hub route handling must resolve bootstrapped remote peers through
  `PeerTunnel.localPeerPort`; websocket registration alone is not enough for
  file, command, terminal, session, or health/debug calls served by the remote
  client.
- Tunnel `ready` is required before presence can move to `starting`.
- The registry is runtime state. It may be cached for diagnostics, but it is
  derived from active SSH tunnel setup and not treated as durable config.
- Reconciliation must release a collaborator's `localPeerPort` when its tunnel
  is closed and no retry is scheduled.

## Code Ownership

Existing SSH code is a starting point, not the final architecture.

| Component | Location | V1 decision |
| --- | --- | --- |
| Onboarding probe | existing SSH probe helper | Keep lightweight form validation. |
| Hub bootstrap worker | new hub-owned module | Own automatic copy/config/runtime/start. |
| Ephemeral forward bootstrap | existing ephemeral manager | May be mined for SSH forwarding mechanics, but hub auto-bootstrap owns lifecycle and health. |

`peer.probe` remains a lightweight pre-add or form validation request. It does
not set presence `online`. `peer.health.get` is the authoritative diagnostics
endpoint for configured collaborators.

Hub auto-bootstrap supersedes local-client `peer.bootstrap` for configured
collaborators. Any existing manual `peer.bootstrap` / `peer.bootstrap.stop`
implementation should be kept only for development/harness use or removed once
the hub worker covers its remaining use cases.

## Bootstrap Worker Lifecycle

The hub reconciles configured collaborators:

- on hub startup
- when collaborator config changes
- when a manual retry endpoint is added and invoked
- after bounded backoff for `offline`, `error`, or stale `online` peers

Worker tasks are cancelled on hub shutdown. V1 uses one bootstrap worker and one
SSH session per collaborator record. Shared SSH control sessions can be an
optimization later.

Default scheduling:

- maximum concurrent bootstrap workers: `2`
- stagger between newly scheduled workers: `250 ms`
- retry: bounded exponential backoff with jitter

## Machine Fingerprint

The first remote command must discover the remote command interpreter and
machine family without assuming bash or Python.

Initial probe:

```text
echo "Linux: $SHELL | Win: %SHELL% / $env:SHELL"
```

Interpretation:

- POSIX `sh`: expands `$SHELL`; leaves `%SHELL%` and `$env:SHELL` mostly
  literal.
- Windows `cmd`: expands `%SHELL%` if set; leaves `$SHELL` and `$env:SHELL`
  literal.
- PowerShell: expands `$env:SHELL`; leaves `%SHELL%` literal.

After the shell family is known, the hub sends a shell-specific diagnostic script
for that dialect. The script should return structured diagnostics including OS,
architecture, required tool availability, writable config area, and install
guidance. V1 does not install missing tools automatically; it returns a
diagnostic payload instead of continuing with setup.

Minimum required tools for v1:

- Python: any usable `python3` or `python` that can run the copied client
  helpers.
- uv: required to run the griplab Python service payload consistently.
- git: required for workspace status, diffs against refs, and repo operations.
- node and npm: required for JavaScript/TypeScript project workflows and local
  UI/dev tooling when the collaborator workspace needs them.

V1 targets developer machines with the full toolchain already installed. Missing
node/npm may later become a warning for Python-only workspaces, but in this
verify-only plan it is reported as an error so the first implementation has a
single clear readiness bar.

For macOS/Linux, the diagnostic script can use POSIX `sh` syntax and commands
such as `uname -s` and `uname -m`. Windows support is not a tested v1 target,
but the fingerprint must let the hub choose a cmd/PowerShell diagnostic path or
return a clear unsupported diagnostic.

## Bootstrap Sequence

For each configured collaborator:

1. Mark health `ssh` as `running`; attempt SSH connection.
2. Run the shell fingerprint command.
3. If SSH or the machine probe fails, mark presence `offline` and health `ssh`
   as `error`.
4. Send the shell-specific diagnostic script.
5. Select the matching client payload for the detected OS/architecture.
6. If Python, uv, git, node, or npm is missing, stop and expose diagnostics
   through `peer.health.get`.
7. From this point, all remote setup/finalize/start commands are Python-driven.
8. Create remote `~/.griplab` with private permissions.
9. Copy the current griplab client payload every time using `scp`. Use a
   temporary target and Python finalization for replacement where the platform
   allows it.
10. Establish or reserve the SSH tunnel pair:
   - remote `-R` from collaborator loopback to hub websocket listener
   - local `-L` from hub loopback to collaborator client service listener
11. Write `~/.griplab/client.json` with:
   - `selfPeerId` from the collaborator record
   - mode `client`
   - workspace root from collaborator `location`
   - hub URL pointing at the remote `-R` loopback forwarded port
   - remote client listen host/port for the `-L` target
   - any required registration token
   - SSH forward metadata from `~/.griplab/forward.json`
12. Start or restart the remote griplab client as an ephemeral process using the
    Python entrypoint from the copied payload.
13. Mark presence `starting` while waiting for `peer.hello`/registration.
14. Mark presence `online` only after the remote client is connected and
    heartbeating through the hub.
15. If startup times out, mark presence `error` and expose details through
    `peer.health.get`.

## Roll-Build Steps

Use a standalone tag prefix for this plan:

```text
collab-bootstrap/step-1-model-health
collab-bootstrap/step-2-ssh-copy-config
collab-bootstrap/step-3-runtime-verify-start
collab-bootstrap/step-4-registration-presence
collab-bootstrap/step-5-health-ui
```

### Step 1: Presence And Health Models

Deliverables:

- Python protocol models for presence and health payloads.
- TypeScript validators/types for `PeerPresence` and `PeerHealth`.
- TypeScript `Peer` migration for `status` and `summary` while preserving
  `online`.
- Snapshot wrapper `{ peers: PeerPresence[] }` for
  `peer.presence.subscribe`.
- `peer.health.get` stub returning hub-local self health plus configured peers.
  The request remains per-peer (`{ peerId }`); it does not become a batch health
  snapshot.
- Config mutation RPC stubs:
  - `peer.collaborator.upsert`
  - `peer.collaborator.remove`
  - optional `peer.collaborator.list`
- Presence records include collaborator config peers with non-online states.
- Hub presence merge logic seeds from config before any `peer.hello`.
- shared collaborator JSON store module used by the hub, config mutation RPCs,
  and CLI/helper scripts for load/upsert/remove behavior.
- Onboarding `peer.probe` remains separate from configured-peer health.
- Active API docs/comments are updated from this plan. Historical design docs in
  `dev-docs/history/archive` are not edited.

Verification:

- Python protocol round-trip tests.
- TypeScript validator tests.
- collaborator loader tests for `collaborators.json`, including SSH auth fields.
- Collaborators page can render configured non-online peers from service mode.

Exit:

- Presence and health payload shape is pinned before SSH code lands.

### Step 2: SSH Reachability, Copy, And Config

Deliverables:

- Hub bootstrap worker skeleton.
- SSH reachability check.
- shell fingerprint and shell-specific diagnostic script.
- Remote `~/.griplab` creation.
- SSH tunnel setup with both:
  - remote `-R` from collaborator loopback back to the hub websocket listener
  - local `-L` from hub loopback to the remote client service listener
- remote and local port allocation from configured safe ranges.
- remote `~/.griplab/forward.json` writer.
- Client payload selection by OS/architecture and copy via `scp` on every
  bootstrap.
- Remote `client.json` writer.
- Health checks for `ssh`, `ssh_tunnel`, `remote_home`, `client_payload`, and
  `config`.

Rules:

- Copy/update runs every bootstrap, not only when a version mismatch is detected.
- V1 client payload copy uses `scp`; do not depend on remote `tar`.
- Remote setup after Python is available is performed by copied Python helper
  scripts, not shell-specific command sequences.
- Use secure temporary directories for staging copied payloads.
- Do not start the remote process yet.

Verification:

- Local SSH harness test creates a remote griplab area.
- shell fingerprint distinguishes POSIX shell, Windows cmd, and PowerShell
  output shapes.
- diagnostics script returns OS, architecture, Python, uv, git, node, npm,
  writable config status, and clear unsupported/missing-tool diagnostics.
- Re-running bootstrap replaces the payload cleanly.
- Harness or mocked SSH-command-builder coverage verifies the combined `-R` and
  `-L` command shape.
- Config content matches collaborator `peerId`, `location`, and forwarded
  loopback hub URL.
- Remote config points at the `-R` loopback hub URL, not a public address.
- `forward.json` and `client.json` agree on the selected remote hub port and
  remote client service port.
- Hub tunnel state records the selected local peer port used for routed service
  calls.
- Failure paths update `peer.health.get`.

Exit:

- The hub can prepare a remote collaborator for startup repeatably.

### Step 3: Runtime Verification And Ephemeral Start

Deliverables:

- Runtime checker for Python, uv, git, node, and npm.
- Python-driven finalize/start helpers in the copied payload.
- Ephemeral remote client start command.
- Health checks for `runtime` and `process`.
- Timeout and retry policy for failed starts.

Rules:

- Missing required tools are v1 `error` health states. Do not install Python,
  uv, git, node, npm, or package-manager dependencies automatically in this
  plan.
- Health diagnostics should include the missing tool name, detected shell/OS,
  and a concise install hint where practical.
- The remote process is ephemeral. Do not create launchd/systemd units in v1.
- Capture remote stdout/stderr into `~/.griplab/logs/` or a hub-readable log tail
  path used by `peer.health.get`.
- The remote start command uses the forwarded loopback hub websocket URL written
  in `client.json`.
- Harness `client.json` may use `registrationToken: null` until the
  registration token/auth model is pinned.
- The remote griplab client listens on remote loopback and provides the normal
  service protocol there. Operations such as terminal open/input/resize, command
  execution, file streams, and session streams are served by that remote client
  protocol and reached by the hub through the `-L` local peer port.
- The hub owns the SSH tunnel session lifetime while the collaborator is
  expected to stay online.

Verification:

- SSH harness starts a remote client process.
- Missing required tool fixtures exercise health diagnostics if the harness can
  model them.
- Start failure and timeout are visible in health diagnostics.

Exit:

- The hub can issue a start and explain startup failures.

### Step 4: Registration, Heartbeat, And Presence

Deliverables:

- Remote client registration includes `peerId`, workspace identity, and client
  version/build id.
- Hub registry links configured collaborator records to live websocket clients.
- Hub route layer resolves collaborator service calls through
  `PeerTunnel.localPeerPort` when the target is a bootstrapped remote peer.
- Heartbeat or equivalent connection liveness.
- Presence stream updates from `starting` to `online` only on live registration.
- Presence returns to `offline` or `error` when the remote client disconnects or
  misses heartbeat.

Verification:

- Local SSH harness proves configured peer becomes online after bootstrap.
- Dropping either SSH forward changes presence away from online.
- Killing the remote process changes presence away from online.
- Re-bootstrap after disconnect returns peer to online.
- Routed probe or lightweight health/debug request through `localPeerPort`
  succeeds after registration.
- Two collaborators on the same SSH address but different `location` and
  `peerId` remain distinct.

Exit:

- Collaborator online/offline status is real and hub-owned.
- Cross-peer relay work must use the tunnel registry endpoint for bootstrapped
  peers before file, command, terminal, or session routing is considered
  complete.

### Step 5: Collaborators Health UI

Deliverables:

- Collaborators page uses service `peer.presence.subscribe`.
- `peersTap.ts` maps `status`, `summary`, and derived `online`.
- Add/remove collaborator flows persist to the hub/config path in service mode
  through `peer.collaborator.upsert` / `peer.collaborator.remove` and trigger
  hub reconcile.
- Add a health/status button per collaborator.
- Health dialog calls `peer.health.get`.
- Dialog renders checks, summary, timestamps, and log tail.
- Mock mode has an explicit mock health provider or keeps collaborator health
  hidden with a documented mock-mode behavior.
- Manual retry button is optional; if added, it calls a dedicated restart
  endpoint rather than overloading health.

Verification:

- Configured offline collaborator renders offline with a health diagnostic.
- Bootstrapping/starting states render without page crashes.
- Online collaborator renders online after registration.
- Health dialog remains usable while presence stream updates.
- Mock mode keeps existing collaborator behavior or has an explicit mock health
  provider.

Exit:

- A user can add collaborators and inspect why a collaborator is not online
  without reading server logs.

## Test Environment

Use `dev-docs/GLTestEnvironDesign.md` and its local SSH harness.

Step 2 may need to extend the harness for reverse forwarding. If full `sshd -R`
coverage is not immediately portable, start with mocked SSH command-builder
tests plus one macOS/Linux integration fixture, then promote it to the normal
harness once stable.

Minimum fixtures:

- SSH unreachable.
- SSH reachable with empty remote griplab area.
- SSH reachable with stale copied payload.
- SSH reachable but `-R` setup fails.
- SSH reachable but `-L` setup fails.
- SSH reachable with two collaborator records pointing to different workspaces.
- remote client exits immediately.
- remote client starts and registers.

Real Raspberry Pi or other developer machines can be used for manual testing,
but automated readiness should not depend on a specific developer host.

## Open Decisions

- Registration token/auth model.

## Roll-Build Placement

This document is the active collaborator-bootstrap roll-build driver. Historical
combined/service/integration plans are archived under `dev-docs/history/archive`
and should not be edited for this work.

Collaborator bootstrap should land before cross-peer workspace/file routing is
considered reliable, because cross-peer features depend on collaborators being
automatically online through the hub.

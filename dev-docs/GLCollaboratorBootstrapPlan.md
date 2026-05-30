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
- Python and uv are not hard prerequisites on the collaborator machine. The hub
  should install or provision the required runtime path when missing.
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
| `bootstrapping` | The hub is copying payload, writing config, or preparing runtime. |
| `starting` | The hub issued the remote client start command and is waiting for registration. |
| `online` | The remote client has connected to the hub and is heartbeating. |
| `error` | Bootstrap/start failed after SSH was reachable. Details live in health. |

Rules:

- SSH reachability alone never means `online`.
- Missing Python, missing uv, missing config, and stale client payload are not
  steady states. They are bootstrap work items.
- The hub may retry `offline`, `error`, and stale `online` peers using bounded
  backoff with jitter.
- The collaborator record remains the configuration source of truth. Live
  client registration is the online source of truth.

## Protocol Surface

### `peer.presence.subscribe`

Presence stream. Payload stays compact enough for always-on UI cards.

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

## Bootstrap Sequence

For each configured collaborator:

1. Mark health `ssh` as `running`; attempt SSH connection.
2. If SSH fails, mark presence `offline` and health `ssh` as `error`.
3. Create remote `~/.griplab` with private permissions.
4. Copy the current griplab client payload every time. Use a temporary target
   and atomic rename where the platform allows it.
5. Write `~/.griplab/client.json` with:
   - `selfPeerId` from the collaborator record
   - mode `client`
   - workspace root from collaborator `location`
   - hub address and any required registration token
6. Check for usable Python and uv.
7. If Python or uv is missing, install/provision the runtime in the remote
   griplab area or invoke the chosen installer.
8. Start or restart the remote griplab client as an ephemeral process.
9. Mark presence `starting` while waiting for `peer.hello`/registration.
10. Mark presence `online` only after the remote client is connected and
    heartbeating through the hub.
11. If startup times out, mark presence `error` and expose details through
    `peer.health.get`.

## Roll-Build Steps

Use the combined services tag prefix unless this work is intentionally split
out:

```text
serv-grip-build/step-8a-collab-model-health
serv-grip-build/step-8b-collab-ssh-copy-config
serv-grip-build/step-8c-collab-runtime-start
serv-grip-build/step-8d-collab-registration-presence
serv-grip-build/step-8e-collab-health-ui
```

### Step 8A: Presence And Health Models

Deliverables:

- Python protocol models for presence and health payloads.
- TypeScript validators/types for `PeerPresence` and `PeerHealth`.
- `peer.health.get` stub returning hub-local self health plus configured peers.
- Presence records include collaborator config peers with non-online states.

Verification:

- Python protocol round-trip tests.
- TypeScript validator tests.
- Collaborators page can render configured non-online peers from service mode.

Exit:

- Presence and health payload shape is pinned before SSH code lands.

### Step 8B: SSH Reachability, Copy, And Config

Deliverables:

- Hub bootstrap worker skeleton.
- SSH reachability check.
- Remote `~/.griplab` creation.
- Client payload copy on every bootstrap.
- Remote `client.json` writer.
- Health checks for `ssh`, `remote_home`, `client_payload`, and `config`.

Rules:

- Copy/update runs every bootstrap, not only when a version mismatch is detected.
- Use secure temporary directories for staging copied payloads.
- Do not start the remote process yet.

Verification:

- Local SSH harness test creates a remote griplab area.
- Re-running bootstrap replaces the payload cleanly.
- Config content matches collaborator `peerId`, `location`, and hub address.
- Failure paths update `peer.health.get`.

Exit:

- The hub can prepare a remote collaborator for startup repeatably.

### Step 8C: Runtime Provisioning And Ephemeral Start

Deliverables:

- Runtime checker for Python and uv.
- Runtime installer/provisioner when missing.
- Ephemeral remote client start command.
- Health checks for `runtime` and `process`.
- Timeout and retry policy for failed starts.

Rules:

- Missing Python/uv is fixed if possible; it is not returned as a final
  `needs_setup` presence state.
- The remote process is ephemeral. Do not create launchd/systemd units in v1.
- Capture remote stdout/stderr into `~/.griplab/logs/` or a hub-readable log tail
  path used by `peer.health.get`.

Verification:

- SSH harness starts a remote client process.
- Missing uv fixture exercises the install/provision branch if the harness can
  model it.
- Start failure and timeout are visible in health diagnostics.

Exit:

- The hub can issue a start and explain startup failures.

### Step 8D: Registration, Heartbeat, And Presence

Deliverables:

- Remote client registration includes `peerId`, workspace identity, and client
  version/build id.
- Hub registry links configured collaborator records to live websocket clients.
- Heartbeat or equivalent connection liveness.
- Presence stream updates from `starting` to `online` only on live registration.
- Presence returns to `offline` or `error` when the remote client disconnects or
  misses heartbeat.

Verification:

- Local SSH harness proves configured peer becomes online after bootstrap.
- Killing the remote process changes presence away from online.
- Re-bootstrap after disconnect returns peer to online.
- Two collaborators on the same SSH address but different `location` and
  `peerId` remain distinct.

Exit:

- Collaborator online/offline status is real and hub-owned.

### Step 8E: Collaborators Health UI

Deliverables:

- Collaborators page uses service `peer.presence.subscribe`.
- Add a health/status button per collaborator.
- Health dialog calls `peer.health.get`.
- Dialog renders checks, summary, timestamps, and log tail.
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

Minimum fixtures:

- SSH unreachable.
- SSH reachable with empty remote griplab area.
- SSH reachable with stale copied payload.
- SSH reachable with two collaborator records pointing to different workspaces.
- remote client exits immediately.
- remote client starts and registers.

Real Raspberry Pi or other developer machines can be used for manual testing,
but automated readiness should not depend on a specific developer host.

## Open Decisions

- Exact client payload format: directory copy, archive upload, or rsync-like
  sync.
- Runtime installer strategy for machines with no Python.
- Registration token/auth model.
- Whether hub restart should immediately bootstrap all collaborators or stagger
  starts with a concurrency limit.
- How much remote log tail to retain in health responses.

## Combined Plan Placement

This work expands `GLCombinedRollBuildPlan.md` Step 8. It should land before
cross-peer workspace/file routing is considered reliable, because cross-peer
features depend on collaborators being automatically online through the hub.

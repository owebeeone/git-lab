# Getting Started

GripLab is a GRIP-based UI for collaborating on software development projects.
The current service path supports a local single-peer workflow, with hub routing
available at the protocol/server layer.

## Prerequisites

- Node.js and npm
- Python 3.11+
- `uv`
- `git`

From the `grip-lab` repo root, install the frontend dependencies if needed:

```bash
npm install
```

The app currently uses local workspace builds of `@owebeeone/grip-core` and
`@owebeeone/grip-react` through `file:` dependencies in `package.json`.

## Run The Mock App

Mock mode does not require a Python service:

```bash
python scripts/start_griplab.py --mock
```

Open the Vite URL printed by the command, usually `http://127.0.0.1:5173/`.

## Run The Local Service App

The normal local service workflow is one command:

```bash
python scripts/start_griplab.py
```

The script uses the default config root:

```text
$GRIPLAB_HOME
```

or, when `GRIPLAB_HOME` is not set:

```text
$HOME/.griplab
```

It creates default `client.json` and `hub.json` there if they do not already
exist. Config directories are private (`0700`), and generated config files are
private (`0600`).

This path exercises workspace status, dependency graph, tree watching, file
streams, sessions, terminals, chat, and local service-backed UI taps.

Useful startup variants:

```bash
# Run TypeScript/Vite build first, then start service dev mode.
python scripts/start_griplab.py --build

# Build and serve the production Vite bundle.
python scripts/start_griplab.py --prod

# Start local service and UI plus the hub.
python scripts/start_griplab.py --with-hub

# Start only the Python local client service.
python scripts/start_griplab.py --no-ui
```

## Start The Hub

Start only the hub from the default config root:

```bash
python scripts/start_griplab.py --hub-only
```

Current state: `griplab hub` accepts `peer.hello`, presence subscriptions,
chat, routed requests, routed subscriptions, and synthetic diff streams. The
local `griplab client` CLI does not yet auto-register itself with the hub as a
peer, so full multi-peer hub mode still needs the peer connector flow or manual
protocol test clients.

## Add A Collaborator Record

Use the helper script to add or update a durable collaborator record:

```bash
python scripts/add_collaborator.py \
  --name "Alice" \
  --ssh-address "alice@example.com:22" \
  --location "~/work/grip-lab"
```

By default, the script writes durable config data under:

```text
$GRIPLAB_HOME
```

or, when `GRIPLAB_HOME` is not set:

```text
$HOME/.griplab
```

The config directory is created with `0700` permissions, and JSON files are
written atomically with `0600` permissions. Transient probe payloads use secure
temporary directories and are deleted when the script exits.

To use a different config root:

```bash
python scripts/add_collaborator.py \
  --config-root path/to/griplab-home \
  --name "Alice" \
  --ssh-address "alice@example.com:22" \
  --location "~/work/grip-lab"
```

To also update a local service config's `peers` list:

```bash
python scripts/add_collaborator.py \
  --service-config "$HOME/.griplab/client.json" \
  --name "Alice" \
  --ssh-address "alice@example.com:22" \
  --location "~/work/grip-lab"
```

To probe over SSH before saving, run through `uv` so `griplab_service` is
importable:

```bash
uv run \
  --with-editable services/griplab_service \
  python scripts/add_collaborator.py \
    --probe \
    --name "Alice" \
    --ssh-address "alice@example.com:22" \
    --location "~/work/grip-lab"
```

## Build And Verify

Frontend checks:

```bash
npm run build
VITE_GL_DATA=service VITE_GL_HUB_ROUTE=1 npm run build
npm run lint
npm test
npm run test:unit
```

Python service checks:

```bash
uv run \
  --with pytest \
  --with-editable services/filedelta \
  --with-editable services/diffstream \
  --with-editable services/griplab_service \
  pytest services/griplab_service/tests -q

uv run --with pytest --with-editable services/diffstream \
  pytest services/diffstream/tests -q

uv run --with pytest --with-editable services/filedelta \
  pytest services/filedelta/tests -q
```

File delta TypeScript checks:

```bash
npm test --prefix services/filedelta-ts
```

Run Python package test directories separately. Some packages share filenames
such as `test_connection.py`, and one combined pytest invocation can trip
pytest's import-name collision behavior.

## Useful URLs And Ports

- Local client websocket: `ws://127.0.0.1:3141/ws`
- Local client health: `http://127.0.0.1:3141/health`
- Hub websocket: `ws://127.0.0.1:3140/ws`
- Hub health: `http://127.0.0.1:3140/health`
- Vite dev server: printed by `npm run dev`

## Performance Diagnostics

The hub and local client keep a small in-memory timing buffer for service-side
operations such as routed subscriptions, tree snapshots, workspace status, and
file window snapshots.

Fetch hub timings:

```bash
uv run --with aiohttp python scripts/griplab_perf.py --url ws://127.0.0.1:3140/ws
```

Fetch timings from a routed collaborator through the hub:

```bash
uv run --with aiohttp python scripts/griplab_perf.py --url ws://127.0.0.1:3140/ws --target weftpi
```

Fetch local client timings directly:

```bash
uv run --with aiohttp python scripts/griplab_perf.py --url ws://127.0.0.1:3141/ws
```

To also emit timing events as JSON lines on service stderr, start the service
with:

```bash
GRIPLAB_TRACE=1 python scripts/start_griplab.py --with-hub
```

When tracing is enabled, JSONL events are also appended to:

```text
scratch/griplab-perf.jsonl
```

Override that path with `GRIPLAB_TRACE_FILE`:

```bash
GRIPLAB_TRACE=1 GRIPLAB_TRACE_FILE=scratch/remote-file-open.jsonl python scripts/start_griplab.py --with-hub
```

## Troubleshooting

- If the service fails to import `filedelta`, `diffstream`, or
  `griplab_service`, use the `uv run --with-editable ...` command shown above.
- If Vite chooses a different port, use the URL printed by `npm run dev`.
- If service mode appears disconnected, confirm `VITE_GL_SERVICE_URL` points at
  the service you actually started.
- If hub route mode reports peers offline, that is expected until a peer has
  connected to the hub websocket and sent `peer.hello`.

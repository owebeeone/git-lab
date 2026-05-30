# GLDiffStreamDesign

Design for GripLab live file diffs. This document supersedes the earlier
roll-build assumption that the browser derives a diff from two independent
`file.subscribe` streams.

## Purpose

Diffs are collaborative objects. The hub should own the canonical diff state so
multiple viewers see the same hunks, anchors, links, refresh behavior, and error
state.

The browser still renders the diff, but it does not coordinate two independent
file subscriptions directly in v1.

## Core Model

A diff is a synthetic stream produced by the hub:

```text
left file stream  \
                   -> hub diff engine -> synthetic diff stream -> browser
right file stream /
```

The hub opens and tracks the two source file streams. Whenever either source
changes, the hub recomputes the diff and publishes an updated structured diff
payload.

The synthetic diff stream behaves like a file stream in the sense that it has:

- a stable `streamId`
- ordered snapshots/resets
- hashable payload bytes
- unsubscribe/cleanup semantics
- a content type

It is not a normal workspace file and should not be addressed through
`file.subscribe`.

## Protocol

`diff.subscribe` is a normal service subscription and uses the standard
websocket envelope from `GLServicesDesign.md`. The client allocates `msgId` and
`streamId`; the hub owns the synthetic `diffId` and payload `version`.

### `diff.subscribe`

Request payload:

```json
{
  "left": {
    "peerId": "me",
    "repoPath": "",
    "path": "src/app.ts",
    "ref": { "kind": "working" }
  },
  "right": {
    "peerId": "alice",
    "repoPath": "",
    "path": "src/app.ts",
    "ref": { "kind": "working" }
  },
  "window": {
    "lineStart": 0,
    "lineEnd": 400
  },
  "contextLines": 3
}
```

Envelope example:

```json
{
  "messageId": "m000001",
  "kind": "request",
  "method": "diff.subscribe",
  "streamId": "s000042",
  "payload": {
    "left": { "peerId": "me", "repoPath": "", "path": "src/app.ts", "ref": { "kind": "working" } },
    "right": { "peerId": "alice", "repoPath": "", "path": "src/app.ts", "ref": { "kind": "working" } },
    "window": { "lineStart": 0, "lineEnd": 400 },
    "contextLines": 3
  }
}
```

Response stream:

- first event: `snapshot`
- later events: `snapshot` or `reset` in v1
- delta updates are optional later, after the structured payload is stable

Stream event envelope:

```json
{
  "messageId": "m000001",
  "kind": "stream-event",
  "method": "diff.subscribe",
  "streamId": "s000042",
  "payload": {
    "streamId": "s000042",
    "seq": 1,
    "event": "snapshot",
    "payload": {}
  }
}
```

Inner event payload:

```json
{
  "contentType": "application/vnd.griplab.diff+json;version=1",
  "diffId": "diff-000001",
  "version": "dv000001",
  "left": {
    "peerId": "me",
    "repoPath": "",
    "path": "src/app.ts",
    "ref": { "kind": "working" },
    "fileVersion": "fv000010",
    "contentHash": "sha256:..."
  },
  "right": {
    "peerId": "alice",
    "repoPath": "",
    "path": "src/app.ts",
    "ref": { "kind": "working" },
    "fileVersion": "fv000007",
    "contentHash": "sha256:..."
  },
  "window": {
    "lineStart": 0,
    "lineEnd": 400,
    "truncated": false
  },
  "hunks": [],
  "unifiedText": null,
  "diagnostics": []
}
```

`contentType` is the payload format source of truth. There is no separate
`format` request field in v1.

### `diff.window.update`

Updates the requested source window for an existing diff stream.

```json
{
  "streamId": "s000042",
  "window": {
    "lineStart": 120,
    "lineEnd": 260
  }
}
```

For v1, window moves may reset the synthetic diff stream. Precise diff deltas are
not required.

### `diff.unsubscribe`

Closes the synthetic diff stream. The hub releases this subscriber and closes the
underlying `DiffConnection` once its reference count reaches zero.

```json
{
  "streamId": "s000042"
}
```

### `diff.get`

`diff.get` remains a one-shot RPC for export, historical comparisons, and
non-live tooling. It should return the same structured payload shape as
`diff.subscribe`, optionally with `unifiedText` populated when requested. It has
no stream lifecycle and is not the primary live diff path.

## Structured Diff Format

The browser needs side-by-side rendering, drag links, focused line anchors, and
possibly hunk-level chat references. The hub should emit structured hunks rather
than only unified diff text.

```json
{
  "id": "h000001",
  "leftStart": 40,
  "leftLines": 6,
  "rightStart": 40,
  "rightLines": 8,
  "lines": [
    {
      "kind": "same",
      "leftNo": 40,
      "rightNo": 40,
      "left": "unchanged",
      "right": "unchanged"
    },
    {
      "kind": "del",
      "leftNo": 41,
      "rightNo": null,
      "left": "removed",
      "right": null
    },
    {
      "kind": "add",
      "leftNo": null,
      "rightNo": 41,
      "left": null,
      "right": "added"
    }
  ]
}
```

Line numbers are one-based display line numbers inside the source file, not
inside the diff output.

The requested `window` remains zero-based and half-open, matching
`GLDeltaFileProtocolLib.md`. Hunk `leftNo` and `rightNo` are absolute one-based
source-file display lines, not window-relative line numbers.

`kind` values:

- `same`
- `add`
- `del`
- `change` can be added later for intraline-aware replacement rows

## Implementation Strategy

### v1 Diff Engine

Use Python stdlib `difflib.SequenceMatcher` plus a structured converter. This
keeps the first implementation dependency-free and testable. Mock and service
mode may produce different row boundaries until the browser mock diff is moved
to the same structured-hunk model; service mode is authoritative.

The hub should compute over decoded text for files identified as text by the
file stream layer. Binary or undecodable inputs return a structured diagnostic
instead of a hunk list.

### Synthetic Resource

Implement a `DiffConnection` or equivalent service object:

- owns left/right routed file subscriptions
- holds the latest valid source payload for each side
- recomputes when either side changes
- publishes synthetic diff snapshots to its subscribers
- closes both source streams on unsubscribe

`DiffConnection` instances are shared and reference counted by a stable diff key:
left endpoint, right endpoint, window, context line count, and content type.
Multiple browser subscribers to the same key receive the same hunk ids and
payload versions.

The payload can be serialized to bytes and hashed, but it does not need to be
written to a real temp file for v1. A temp/debug file is acceptable later if it
helps inspect or reuse the filedelta machinery.

### Hub Relay And Recompute Policy

The synthetic diff stream runs in the hub. Same-peer and cross-peer diffs use
the same path: the hub opens routed source file subscriptions for both endpoints
using the Step 10 relay contract.

Source stream events are serialized through the `DiffConnection`. If both sides
change concurrently, the hub coalesces pending changes and publishes one snapshot
after both current source states are valid. A short debounce, for example 16 ms,
is acceptable to avoid redundant recomputes during bursts. The hub must never
publish a diff snapshot computed from a partially applied source delta.

If either source is mid-reset, the diff stream reports a diagnostic until both
source sides have fresh valid snapshots.

### Updates

For v1:

- source file update -> recompute and send full synthetic diff snapshot
- source stream reset -> recompute after both sides are valid again
- source stream error -> emit diff diagnostic snapshot or stream error
- diff window move -> reset/recompute

Do not attempt structured diff deltas until the snapshot format and renderer are
stable.

## Browser Mapping

Add a service tap such as `diffContentTap.ts` using
`createAsyncStreamMultiTap`.

Suggested grips:

- `DIFF_HUNKS`
- `DIFF_STREAM_STATUS`
- `DIFF_DIAGNOSTICS`
- `DIFF_VERSION`

Inputs:

- `SELECTED_FILE`
- `DIFF_LEFT`
- `DIFF_RIGHT`
- a diff window grip, likely separate from `FILE_WINDOW`

Request keys include selected file, left endpoint, right endpoint, window, and
destination context key. `DiffViewerView` should use a keyed context such as
`diff:main` so stream lifecycle and local state are isolated from file viewer
panes.

The browser sends debounced `diff.window.update` messages for scroll/window
changes. It does not open the two source file streams itself in service mode.

## Renderer Options

Open question: whether to use an existing browser diff renderer or keep the
current custom side-by-side renderer.

Default recommendation for v1:

- keep the current custom renderer shape
- replace its input with structured hunks from `diff.subscribe`
- retain GripLab-specific drag links, focus-line behavior, peer labels, and
  state links

Potential later renderer/tooling work:

- evaluate JS libraries that accept unified diff text
- optionally include `unifiedText` in the hub payload for export/tool
  compatibility
- add intraline highlighting once the hunk format has settled

## Links And Anchors

Diff links should identify both endpoints plus an anchor:

```json
{
  "diffId": "diff-000001",
  "hunkId": "h000001",
  "side": "left",
  "line": 41
}
```

v1 state links continue carrying `Lab.DiffLeft`, `Lab.DiffRight`,
`Lab.SelectedFile`, and `Lab.FocusLine`. Hunk ids are stable only for one
synthetic payload version unless they are later derived from content hashes and
source line ranges. Do not treat hunk ids as durable chat targets in v1.

v2 may add a `Lab.DiffAnchor` grip with `{ diffId, version, hunkId, side, line }`
once hunk-id stability rules are defined.

## Diagnostics

Diagnostic shape:

```json
{
  "code": "missing-file",
  "message": "right file does not exist",
  "endpoint": "right",
  "details": {}
}
```

Initial v1 codes:

| Code | Meaning |
| --- | --- |
| `missing-file` | One side cannot open the requested file |
| `binary-file` | One or both sides are binary |
| `decode-failed` | Text decoding failed |
| `window-truncated` | Requested window exceeded service caps |
| `peer-offline` | Routed source peer is unavailable |
| `unsupported-ref` | Source peer cannot serve the requested ref |

When diagnostics are present, `hunks` may be empty or partial. `unifiedText` is
`null` unless explicitly requested and safely available.

## Error And Edge Cases

- Missing left or right file: structured diagnostic with the missing endpoint.
- Binary file: diagnostic snapshot; no hunks.
- Decode failure: diagnostic snapshot with encoding details if known.
- Huge file/window over cap: truncated diagnostic and partial hunks when safe.
- Peer offline: routed source stream error, surfaced as diff diagnostic.
- Ref unsupported by source peer: diagnostic for that endpoint.

## Verification

Python tests:

- structured hunk conversion for same/add/delete/replace cases
- missing left/right endpoint diagnostics
- binary and decode-failure diagnostics
- window truncation diagnostic
- `DiffConnection` coalesces concurrent left/right updates into ordered
  snapshots
- shared `DiffConnection` reference count closes source streams after the last
  subscriber

TypeScript/front-end tests:

- protocol parser accepts `diff.subscribe` payloads and structured snapshots
- `diffContentTap` maps snapshots to diff grips
- `DiffViewerView` renders structured hunks without `fakeData` in service mode
- state links still restore selected file, endpoints, and focus line

Integration tests:

- two local service peers through the hub produce a routed synthetic diff
- source file edit on either peer updates the diff stream
- peer disconnect produces a structured diagnostic or stream error

## Roll-Build Impact

`GLCombinedRollBuildPlan.md` should use these cross-peer diff steps:

1. relay contract
2. cross-peer file streams
3. hub synthetic diff stream
4. browser diff renderer integration
5. remote commands

The old client-derived diff step should be treated as fallback only, not the
target architecture.

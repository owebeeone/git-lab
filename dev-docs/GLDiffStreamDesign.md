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

### `diff.subscribe`

Request:

```json
{
  "left": {
    "peerId": "me",
    "repoPath": "",
    "path": "src/app.ts",
    "ref": "working"
  },
  "right": {
    "peerId": "alice",
    "repoPath": "",
    "path": "src/app.ts",
    "ref": "working"
  },
  "window": {
    "lineStart": 0,
    "lineEnd": 400
  },
  "contextLines": 3,
  "format": "structured-diff-v1"
}
```

Response stream:

- first event: `snapshot`
- later events: `snapshot` or `reset` in v1
- delta updates are optional later, after the structured payload is stable

Event payload:

```json
{
  "contentType": "application/vnd.griplab.diff+json;version=1",
  "diffId": "diff-000001",
  "version": "dv000001",
  "left": {
    "peerId": "me",
    "repoPath": "",
    "path": "src/app.ts",
    "ref": "working",
    "fileVersion": "fv000010",
    "contentHash": "sha256:..."
  },
  "right": {
    "peerId": "alice",
    "repoPath": "",
    "path": "src/app.ts",
    "ref": "working",
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

`kind` values:

- `same`
- `add`
- `del`
- `change` can be added later for intraline-aware replacement rows

## Implementation Strategy

### v1 Diff Engine

Use Python stdlib `difflib.SequenceMatcher` or `difflib.unified_diff` plus a
structured converter. This keeps the first implementation dependency-free and
testable.

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

The payload can be serialized to bytes and hashed, but it does not need to be
written to a real temp file for v1. A temp/debug file is acceptable later if it
helps inspect or reuse the filedelta machinery.

### Updates

For v1:

- source file update -> recompute and send full synthetic diff snapshot
- source stream reset -> recompute after both sides are valid again
- source stream error -> emit diff diagnostic snapshot or stream error
- diff window move -> reset/recompute

Do not attempt structured diff deltas until the snapshot format and renderer are
stable.

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

Existing state links can continue carrying `Lab.DiffLeft`, `Lab.DiffRight`,
`Lab.SelectedFile`, and `Lab.FocusLine`. Once hub diff streams exist, links
should prefer hunk ids when available, with line fallback when the diff has
changed.

## Error And Edge Cases

- Missing left or right file: structured diagnostic with the missing endpoint.
- Binary file: diagnostic snapshot; no hunks.
- Decode failure: diagnostic snapshot with encoding details if known.
- Huge file/window over cap: truncated diagnostic and partial hunks when safe.
- Peer offline: routed source stream error, surfaced as diff diagnostic.
- Ref unsupported by source peer: diagnostic for that endpoint.

## Roll-Build Impact

`GLCombinedRollBuildPlan.md` should change the cross-peer diff steps to:

1. relay contract
2. cross-peer file streams
3. hub synthetic diff stream
4. browser diff renderer integration
5. remote commands

The old client-derived diff step should be treated as fallback only, not the
target architecture.

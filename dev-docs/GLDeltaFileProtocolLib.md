# GLDeltaFileProtocolLib

Standalone file delta protocol library for grip-lab. This document is the
authoritative design for the **pure** file snapshot/delta/apply core and the
**FileConnection** / **FileWindowSubscription** runtime that holds live
attachments to file sources and projected line windows.

See also:

- `dev-docs/GLServicesDesign.md` — hub/local client, websocket transport,
  `file.subscribe` / `file.window.update`, watchdog tree monitoring
- `dev-docs/GLCodingRules.md` — dependency-age policy for PyPI packages

## Purpose

The library answers: given a file on disk and a sequence of changes (or window
projection updates), how do we produce and apply **ordered, hash-validated byte
deltas** reliably?

It does **not**:

- Subscribe to filesystem or watchdog services
- Know about websockets, FastAPI, GRIP, git, or workspace discovery
- Run its own background polling loop

It **does**:

- Hold a **source connection** to one file path (track `fileVersion`, baseline)
- Hold **window subscriptions** projecting line ranges into byte blobs
- Accept **external file-change notifications** (`file_changed()`)
- Accept **window projection updates** (`update_window()`)
- Emit sequential deltas to downstream subscribers
- Notify subscribers when listening starts or stops

The grip-lab **service layer** owns watchdog, git adapters, websocket fanout, and
permission checks.

## Async-first

All public runtime APIs in this library and in grip-lab hub/local client code
use **`asyncio` + `async def`**. File I/O uses `asyncio.to_thread()` where
needed. Sync pure functions (`diff_bytes`, `apply_ops`) remain sync for tests.

## Package boundary

```text
services/
  filedelta/
    pyproject.toml
    src/filedelta/
      __init__.py
      model.py          # FileSource, LineWindow, snapshots, deltas, scope
      ops.py            # shared byte-op model
      snapshot.py       # make_full_snapshot, make_window_snapshot
      diff.py           # diff_bytes, diff_window_snapshots
      apply.py          # apply_delta, apply_window_delta (pure)
      hash.py
      connection.py     # FileConnection (async, source)
      window.py         # FileWindowSubscription (async)
      subscriber.py
      testing.py
    tests/
      test_ops.py
      test_full_snapshots.py
      test_window_snapshots.py
      test_sequences.py
      test_connection.py
      test_window_grow_shrink.py
  griplab_service/
    src/griplab_service/
      file_watch_adapter.py
      git_status_adapter.py
      ws_file_streams.py
```

**Import rule:** grip-lab may import `filedelta`; `filedelta` must not import
grip-lab, FastAPI, websockets, GRIP, watchdog, or git code.

---

## 1. Shared byte-op model

Ops apply in array order to a **byte buffer** (the payload for the current
`scope`).

| Op | Fields | Effect |
| --- | --- | --- |
| `replace` | `offset`, `length`, `data` | Delete `length` bytes at `offset`, insert `data` |
| `insert` | `offset`, `data` | Insert `data` at `offset` |
| `delete` | `offset`, `length` | Remove `length` bytes at `offset` |

Rules:

- Ops must not overlap within one delta (producer responsibility)
- After all ops, buffer hash must equal the declared result hash
- **Byte ops always apply to the payload scope**, not implicitly to the full file
- Text decoding is never part of delta validity

```python
def diff_bytes(old: bytes, new: bytes) -> list[Op]: ...
def apply_ops(data: bytes, ops: list[Op]) -> bytes: ...
```

---

## 2. File source identity and versioning

### FileSource

```json
{
  "resourceId": "alice:alice-main:yidl:src/yidl/cli.py:working",
  "repoPath": "yidl",
  "path": "src/yidl/cli.py",
  "ref": { "kind": "working" }
}
```

### LineWindow

Zero-based, half-open line ranges internally (`lineStart` included,
`lineEnd` excluded). UI may display one-based labels.

```json
{
  "lineStart": 0,
  "lineEnd": 240
}
```

### Version fields

| Field | Meaning |
| --- | --- |
| `fileVersion` | Source file version (`fv000001`, …) |
| `windowVersion` | Projected window version (`wv000001`, …); only for `text-window` |
| `seq` | Stream event order per subscription |

`kind` classifies the file (`text`, `binary`, `metadata-only`).
`scope` classifies the payload (`full`, `text-window`, `metadata-only`).

---

## 3. Full-file snapshots and deltas

For small files, tests, and explicit full subscribers.

### Full snapshot (`scope: "full"`)

```json
{
  "scope": "full",
  "resourceId": "alice:alice-main:yidl:src/yidl/cli.py:working",
  "fileVersion": "fv000001",
  "contentHash": "sha256:...",
  "kind": "text",
  "size": 1234,
  "encoding": "utf-8",
  "newline": "lf",
  "data": "base64:...",
  "lineIndex": [0, 12, 30],
  "metadata": {}
}
```

### Full delta (`scope: "full"`)

```json
{
  "scope": "full",
  "resourceId": "alice:alice-main:yidl:src/yidl/cli.py:working",
  "seq": 2,
  "baseFileVersion": "fv000001",
  "resultFileVersion": "fv000002",
  "baseHash": "sha256:...",
  "resultHash": "sha256:...",
  "ops": [
    { "op": "replace", "offset": 10, "length": 5, "data": "base64:..." }
  ],
  "metadata": {}
}
```

Apply validation: `seq == last_seq + 1`, `baseFileVersion` and `baseHash` match
held snapshot, ops valid, `resultHash` matches.

---

## 4. Text-window snapshots and deltas

### Window projection

```text
full file version → projected line window → byte snapshot/delta of window bytes
```

- **Request shape:** line-oriented (client requests line ranges)
- **Payload shape:** byte-oriented (raw bytes for complete lines, base64 in JSON)
- **Delta shape:** byte ops over the **current window blob**, not the whole file

The editor usually needs visible lines + overscan, not the entire file. Line
ranges select content; byte ops patch the projected blob.

### Text-window snapshot (`scope: "text-window"`)

```json
{
  "scope": "text-window",
  "resourceId": "alice:alice-main:yidl:src/yidl/cli.py:working",
  "windowId": "w-000001",
  "fileVersion": "fv000010",
  "windowVersion": "wv000001",
  "fileHash": "sha256:...",
  "windowHash": "sha256:...",
  "lineStart": 100,
  "lineEnd": 260,
  "totalLines": 1200,
  "startByte": 4812,
  "endByte": 12044,
  "encoding": "utf-8",
  "newline": "lf",
  "data": "base64:...",
  "lineIndex": [0, 44, 88],
  "truncated": false,
  "metadata": { "gitStatus": "modified" }
}
```

- `windowHash` — hash of window bytes (the `data` payload)
- `fileHash` — optional; may be omitted for huge/metadata-only sources
- `startByte` / `endByte` — byte offsets in the full file at this `fileVersion`
- `lineIndex` — byte offsets **relative to the window blob**
- `truncated` — true if window exceeded `windowBytesCap` and was clamped

### Text-window delta (`scope: "text-window"`)

```json
{
  "scope": "text-window",
  "resourceId": "alice:alice-main:yidl:src/yidl/cli.py:working",
  "windowId": "w-000001",
  "seq": 12,
  "reason": "file-change",
  "baseFileVersion": "fv000010",
  "resultFileVersion": "fv000011",
  "baseWindowVersion": "wv000004",
  "resultWindowVersion": "wv000005",
  "baseWindowHash": "sha256:...",
  "resultWindowHash": "sha256:...",
  "lineStart": 100,
  "lineEnd": 260,
  "totalLines": 1201,
  "startByte": 4812,
  "endByte": 12080,
  "ops": [
    { "op": "replace", "offset": 60, "length": 12, "data": "base64:..." }
  ],
  "lineIndex": [0, 44, 91],
  "metadata": { "gitStatus": "modified" }
}
```

Apply validation:

- `seq == last_seq + 1`
- `baseWindowVersion == current.windowVersion`
- `baseWindowHash == hash(current.windowBytes)`
- apply ops to window blob → `resultWindowHash` matches
- advance `windowVersion`; record `resultFileVersion`, line/byte bounds, `lineIndex`

Consumer does **not** need full-file bytes to apply a window delta.

### Line terminator semantics

- A line window contains **complete logical lines**
- Line bytes include their terminator when present (CRLF preserved in bytes)
- The final unterminated line is still a line
- `newline` metadata is descriptive; no normalization in the protocol core
- Client decodes window bytes to text **after** hash-validated apply:

```text
window bytes → decode using snapshot encoding → syntax highlight/render
```

Decode failure must not corrupt delta application. Show replacement characters
or switch to binary/metadata-only display per policy.

### Grow and shrink (window projection changes)

Window changes use the same byte-op machinery but are **not** filesystem changes.

**Grow** (e.g. lines `100..260` → `80..300`): insert prefix/suffix bytes into
the current window blob, or send `reset`.

```json
{
  "scope": "text-window",
  "reason": "window-grow",
  "lineStart": 80,
  "lineEnd": 300,
  "ops": [
    { "op": "insert", "offset": 0, "data": "base64:<lines 80..99>" },
    { "op": "insert", "offset": 9000, "data": "base64:<lines 260..299>" }
  ]
}
```

**Shrink** (e.g. `80..300` → `100..260`): delete bytes from the window blob, or
send `reset`.

Delta is an optimization; **reset is always legal**.

### File change semantics for windows

When the file changes, do **not** diff the whole file for every window
subscriber:

1. Advance source `fileVersion`
2. Reproject the subscriber's requested `lineStart`/`lineEnd` against the new file
3. Diff old window blob vs new projected window blob
4. Emit a window byte delta (or metadata-only delta, or nothing)

| Situation | Action |
| --- | --- |
| Edit inside window | Byte ops on window blob |
| Edit before window (same logical line range) | Updated `totalLines`, `startByte`, `endByte`, `fileVersion`; byte ops if range content changed |
| Edit after window | Metadata-only delta if offsets/totals changed; else nothing |
| Change outside window, bytes unchanged | Metadata-only delta (no ops) acceptable |
| Mass change / overflow | `reset` |

**v1 line-window policy:** window ranges are logical line-number ranges in the
current file version. After a file change, the server reprojects the same
requested `lineStart`/`lineEnd` against the new file version.

Future anchor policies: keep top visible line by content, cursor-stable, tail-follow
for logs, diff-hunk anchor.

---

## 5. Metadata-only snapshots

When a file exceeds caps or is binary-only:

```json
{
  "scope": "metadata-only",
  "resourceId": "...",
  "fileVersion": "fv000001",
  "kind": "binary",
  "size": 50000000,
  "metadata": { "executable": false }
}
```

No inline `data`. Window mode is not available unless a text window fits under
`windowBytesCap`.

### Large-file policy

| Cap | Default use |
| --- | --- |
| `fullContentSizeCap` | Full snapshot allowed under this size |
| `windowBytesCap` | Text-window snapshot allowed under this size |

- File too large for full snapshot but text → **text-window mode**
- Requested window exceeds `windowBytesCap` → `err` or clamp with `truncated: true`
- Very large files may need sparse line indexing to locate line ranges

---

## 6. Baseline read strategies

Full-file streams use COW full reads under `fullContentSizeCap`:

```python
async def read_cow_full(path: Path) -> bytes:
    def _read() -> bytes:
        with open(path, "rb") as f:
            with mmap.mmap(f.fileno(), length=0, access=mmap.ACCESS_COPY) as mm:
                return bytes(mm)
    return await asyncio.to_thread(_read)
```

Text-window streams may **read only projected byte ranges** after locating line
offsets. Keep a per-window old projected byte blob for diffing. Small files may
still use full COW reads internally.

Fallback: temp copy or deleted-inode buffer for symlinks, FIFOs, or mmap failure.

---

## 7. FileConnection and FileWindowSubscription lifecycle

### Separation of concerns

- **`FileConnection`** — owns source file path, `fileVersion`, current full-file
  baseline (or line index for window projection). Receives `file_changed()`.
- **`FileWindowSubscription`** — owns one subscriber's projected window bytes,
  `windowVersion`, and `seq`. Receives `update_window()`.

```python
class FileConnection:
    async def open(self) -> None: ...
    async def close(self, reason: str = "closed") -> None: ...
    async def file_changed(self, reason: str = "external") -> None: ...
    async def subscribe_window(
        self, sub: FileSubscriber, window: LineWindow
    ) -> FileWindowSubscription: ...

class FileWindowSubscription:
    async def update_window(self, window: LineWindow) -> None: ...
    async def close(self, reason: str = "closed") -> None: ...
```

`file_changed()` notifies all window subscriptions to reproject and emit deltas.
`update_window()` is a **subscription projection change**, not a filesystem event.

### Subscriber callbacks

```python
class FileSubscriber(Protocol):
    async def on_listening(self, resource_id: str) -> None: ...
    async def on_stop_listening(self, resource_id: str, reason: str) -> None: ...
    async def on_snapshot(self, snapshot: Snapshot) -> None: ...
    async def on_delta(self, delta: Delta) -> None: ...
    async def on_reset(self, snapshot: Snapshot, reason: str) -> None: ...
    async def on_error(self, code: str, message: str) -> None: ...
```

### Sequential apply contract

**Producer:** initial `snapshot` (seq 0); then `delta` with seq += 1; never skip
seq; emit `reset` when patching forward is unsafe.

**Consumer:** validate seq and base version/hash; apply; on failure **close and
reopen** (unsubscribe + resubscribe). Do not repair partial state.

### WS mapping (service layer)

| Filedelta callback | WS event |
| --- | --- |
| `on_listening` | optional `progress`, or omitted |
| `on_snapshot` | `snapshot` |
| `on_delta` | `delta` |
| `on_reset` | `reset` |
| `on_error` | `err` |
| `on_stop_listening` | `end` |

Per-subscriber queue limits and lagging-consumer reset are **websocket layer**
responsibilities. Filedelta emits sequential deltas; WS decides when to drop
and send `reset`.

---

## 8. Reset and error rules

| Reason | Typical source |
| --- | --- |
| `initial` | First snapshot |
| `file-change` | Source file changed; window reprojected |
| `window-grow` | Client expanded line range |
| `window-shrink` | Client reduced line range |
| `window-move` | Client moved line range |
| `window-policy-reset` | Anchor policy change (future) |
| `watchdog-overflow` | Watcher queue dropped events |
| `mass-change` | Checkout, merge, many files |
| `mode-change` | Text/binary flip |
| `size-cap` | Exceeds content cap |
| `hash-mismatch` | Drift detected |
| `deleted-recreated` | Path reused |
| `consumer-resync` | Client requested realignment |
| `producer-overflow` | WS queue dropped |

Resets are **normal**. Delta is an optimization over reset, never required for
correctness.

---

## 9. Pure API

```python
def make_full_snapshot(source: FileSource, data: bytes, metadata: dict) -> FullSnapshot: ...
def make_window_snapshot(
    source: FileSource, data: bytes, window: LineWindow, metadata: dict,
    *, total_lines: int, start_byte: int, end_byte: int,
) -> TextWindowSnapshot: ...
def diff_snapshots(old: FullSnapshot, new: FullSnapshot) -> FullDelta: ...
def diff_window_snapshots(old: TextWindowSnapshot, new: TextWindowSnapshot) -> TextWindowDelta: ...
def apply_full_delta(snapshot: FullSnapshot, delta: FullDelta) -> FullSnapshot: ...
def apply_window_delta(snapshot: TextWindowSnapshot, delta: TextWindowDelta) -> TextWindowSnapshot: ...
def validate_snapshot(snapshot: Snapshot) -> None: ...
```

Text diff: stdlib `difflib` or **`rapidiff`**. Binary: **`detools`** or reset-only.

---

## 10. Service integration (not in this library)

```text
watchdog event     → file_watch_adapter → FileConnection.file_changed("watchdog")
git HEAD move      → git_status_adapter → FileConnection.file_changed("head")
file.window.update → ws_file_streams    → FileWindowSubscription.update_window()
file.subscribe     → ws_file_streams    → open connection + window subscription
```

Tree monitoring (`tree.subscribe`) does not use `FileConnection`.

---

## 11. Model invariants

- `scope: "full"` ops apply to full file bytes
- `scope: "text-window"` ops apply to window bytes only
- Line windows are half-open, zero-based internally
- Window bytes contain whole lines only
- `lineIndex` is relative to the payload bytes
- A window delta may update metadata with **no ops**
- Reset is always legal
- Text decoding never affects delta validity

---

## 12. Test matrix

**Full-file:** empty, one-line, many-line, CRLF, trailing newline, UTF-8 multibyte,
random edit sequences, wrong base hash/version, out-of-order seq, COW regression.

**Text-window:**

- Initial window `0..N`
- Grow at beginning/end; shrink at beginning/end
- Move window (delta or reset)
- File edit inside / before / after window
- Insert/delete before window updates `totalLines` and offsets
- CRLF windows preserve CRLF bytes
- Final unterminated line included
- UTF-8 multibyte never breaks byte apply
- Decode failure does not break byte apply
- Window over cap errors or truncates
- Two subscribers, different windows, independent `windowVersion` and seq
- Grow/shrink deltas validate `baseWindowHash`
- Metadata-only window deltas (no ops)
- Reset from window to metadata-only mode

Property-style: deterministic random line-window changes interleaved with random
file edits.

---

## 13. Resolved decisions

| Topic | Decision |
| --- | --- |
| Core coordinates | Byte offsets |
| Text request shape | Client requests line windows |
| Text payload | Raw line bytes, base64 in JSON |
| Text delta | Byte ops over current window blob |
| Full-file mode | Small files, tests, explicit full subscribers |
| Large text mode | Text-window snapshots/deltas |
| Window grow/shrink | Delta preferred; reset always legal |
| File change | Reproject window, diff window blobs |
| Decode | Client-side after apply |
| Line numbering | Zero-based half-open internal; one-based display |
| Versioning | Separate `fileVersion` and `windowVersion` |
| Connection split | `FileConnection` (source) + `FileWindowSubscription` (projection) |
| Baseline read | Full COW under cap; range read for windows |

## 14. Still open (minor)

- Exact `fullContentSizeCap` and `windowBytesCap` defaults
- Sparse line index strategy for very large files
- Binary patch ops in v1 or reset-only
- Future anchor policies beyond v1 logical-line reprojection

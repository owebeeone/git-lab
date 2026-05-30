# GLDeltaFileWindowProtocol Plan

Implementation plan for the standalone `filedelta` library described in
`dev-docs/GLDeltaFileProtocolLib.md`.

This is a roll-build-compatible plan. It defines checkpoints that can be built,
verified, committed, and tagged one at a time. Do not start the roll-build from
this plan unless the working tree is clean and a phase-start tag has been chosen.

## Readiness

The design is ready for planning. The remaining open items are implementation
parameters, not design blockers. Phases 1-2 can start immediately. Pin the
implementation parameters below before Phase 3 window-delta generation.

- whether binary patches beyond structured byte ops are needed later
- property-test dependency choice

## Delta Algorithm Decision

### Recommendation: structured byte ops for v1

Use the project-owned structured byte-op protocol for v1:

```json
{ "op": "replace", "offset": 60, "length": 12, "data": "base64:..." }
```

Python generates ops. TypeScript applies ops to `Uint8Array`. Text-window
payloads are raw bytes for complete logical lines; decoding happens after
validated reassembly.

### Why not VCDIFF first?

VCDIFF would not remove most of the testing burden. We would still need tests
for:

- initial window construction
- reset handling
- grow and shrink
- line insertion/removal before, inside, and after the window
- truncation
- metadata-only deltas
- file/window version sequencing
- browser-side reassembly and decoding

VCDIFF only replaces the byte-op apply step. It adds toolchain and interop risk:

- Python generation would likely use an external `xdelta3`/open-vcdiff adapter
  or subprocess.
- Browser decode would depend on an npm decoder.
- Payloads become opaque, harder to inspect, and harder to debug during protocol
  development.

Therefore v1 should use structured byte ops. Add a codec abstraction so VCDIFF
or another codec can be evaluated later from real metrics.

### Future codec hook

Keep this field in protocol data structures:

```json
{ "codec": { "name": "structured-byte-ops", "version": 1 } }
```

Later candidates can include:

- `vcdiff` for larger binary/window payloads
- a compact binary encoding of the same structured ops

Do not implement those in v1 unless structured ops fail measured performance
targets.

## Implementation Parameters

Pin these before starting Phase 3. Phases 1-2 can start without them.

| Parameter | v1 decision | Notes |
| --- | --- | --- |
| `fullContentSizeCap` | 1 MiB | Full snapshots/deltas only under this cap unless explicitly overridden in tests. |
| `windowBytesCap` | 256 KiB | Text-window payload cap after overscan. |
| Window over cap | Clamp with `truncated: true` | Hard errors are reserved for invalid ranges or unsupported files. Clamp keeps the editor usable. |
| Grow/shrink policy | Prefer structured delta when added/removed bytes <= 64 KiB; otherwise reset | Delta is an optimization. Reset remains always legal. |
| Window move policy | Reset by default | A later optimization may express moves as delete+insert. |
| File-change policy | Reproject requested logical line range; send delta if changed bytes <= 64 KiB, else reset | Metadata-only delta is allowed when window bytes are unchanged. |
| Deleted file policy | Emit `on_error(code="deleted")` and close | Recreate at same path opens a fresh stream via resubscribe. |
| Line-index strategy | Full scan under 10 MiB; sparse index beyond that | Sparse index can be coarse initially and refined around requested windows. |
| `fileVersion` / `windowVersion` | Increment by one per accepted source/window state change | Format `fv000001`, `wv000001`; resets still advance version. |
| `seq` | Per subscription stream; initial snapshot seq 0, deltas start at 1 | Reset carries stream seq and replacement snapshot. |
| Phase 1-3 dependencies | Python stdlib only | Do not add `rapidiff`, VCDIFF, or property-test deps before the core protocol is stable. |
| `diff.py` first implementation | Simple prefix/suffix byte diff | Good enough for small windows; can emit one replace op for middle changes. |

The prefix/suffix diff rule is:

1. Find the common prefix.
2. Find the common suffix after the prefix.
3. Emit one `replace`, `insert`, or `delete` for the changed middle region.

This is intentionally simple and highly testable. Smarter diffing is a later
payload-size optimization, not required for correctness.

## Target Package Shape

Python source belongs under top-level `services/`, not under the existing
frontend `src/` tree. In this repo, `src/` is the Vite/React/TypeScript app.
Keeping Python under `services/` prevents frontend tooling from owning backend
source and keeps the pure delta library excisable.

```text
grip-lab/
  src/                         # existing frontend only
  services/
    filedelta/
      pyproject.toml
      src/filedelta/
        __init__.py
        model.py
        ops.py
        snapshot.py
        diff.py
        apply.py
        hash.py
        line_index.py
        connection.py
        window.py
        subscriber.py
        testing.py
      tests/
        ...
    filedelta-ts/
      package.json
      src/
        model.ts
        ops.ts
        apply.ts
        reassembler.ts
        decode.ts
      tests/
        ...
```

The `services/filedelta` package is the canonical Python source location for
the delta protocol. The `services/filedelta-ts` package is the TypeScript
reassembler/validator location unless implementation chooses to fold those
modules into the app's existing frontend package. The import rule is fixed:
`filedelta` must not import grip-lab service code, FastAPI, websockets, GRIP,
watchdog, or git code.

Decision point before Phase 4: either keep TypeScript support in
`services/filedelta-ts` or fold it into a frontend module such as
`src/lab/serviceClient/filedelta/`. Pick one location before writing the TS
reassembler tests so fixture paths and verification commands stay stable.

## Protocol Data Structures

Implement matching Python and TypeScript structures for these concepts.

### Shared model

- `CodecDescriptor`
- `FileSource`
- `LineWindow`
- `ByteOp`
- `FileMetadata`
- `Snapshot`
- `Delta`
- `ResetReason`
- `DeltaReason`

Python:

- Use dataclasses or pydantic models. Prefer plain dataclasses for the pure
  package unless validation ergonomics require pydantic.
- Provide `to_json_dict()` / `from_json_dict()` helpers if using dataclasses.

TypeScript:

- Provide interfaces plus runtime validators for external payloads.
- Do not trust JSON from the wire solely because it matches TypeScript types.

### Snapshot variants

- `FullSnapshot`
- `TextWindowSnapshot`
- `MetadataOnlySnapshot`

Required fields:

- `scope`
- `resourceId`
- `fileVersion`
- `kind`
- size and metadata
- `data` only when content bytes are present
- hashes for the applicable payload

Text-window fields:

- `windowId`
- `windowVersion`
- `lineStart`
- `lineEnd`
- `totalLines`
- `startByte`
- `endByte`
- `lineIndex`
- `truncated`

### Delta variants

- `FullDelta`
- `TextWindowDelta`
- `MetadataOnlyDelta`

Required fields:

- `scope`
- `resourceId`
- `seq`
- base/result versions
- base/result hashes for the payload scope
- `codec`
- `ops`
- updated metadata

For text-window deltas, ops apply to the current window bytes, not full-file
bytes.

## Python Test Plan

Python tests should validate generation, application, sequencing, and
connection/window lifecycle.

Use focused unit tests for mechanics and canonical fixture tests for end-to-end
window behavior. Avoid duplicating the same success case in both styles.

### Phase P1: byte ops core

Tests:

- insert into empty bytes
- insert at beginning/middle/end
- delete at beginning/middle/end
- replace shorter/same/longer
- multiple non-overlapping ops
- invalid negative offset
- invalid range past end
- overlapping ops rejected
- result hash mismatch rejected

Verification:

- `pytest services/filedelta/tests/test_ops.py`

### Phase P2: full snapshots and deltas

Tests:

- empty file snapshot
- one-line file snapshot
- many-line file snapshot
- CRLF preserved
- UTF-8 multibyte preserved
- append bytes
- truncate file
- wrong base version rejected
- wrong base hash rejected
- reset snapshot validates

Verification:

- focused full snapshot/delta tests

### Phase P3: line index and text windows

Tests:

- line index for LF
- line index for CRLF
- final unterminated line
- initial window at start
- initial window in middle
- initial window at EOF
- window over file end clamps with `truncated: true`
- window bytes contain complete logical lines
- `lineIndex` is relative to window bytes

Verification:

- line index tests
- text-window snapshot fixture tests

### Phase P4: window reassembly mechanics

Tests required by design:

- start: initial window snapshot reassembles expected bytes
- reset: reset replaces current window
- grow at end
- grow at beginning
- shrink at end
- shrink at beginning
- move window, delta or reset by policy
- lines changed inside window
- lines inserted inside window
- lines inserted before window
- lines inserted after window
- lines removed inside window
- lines removed before window
- lines removed after window
- file truncated inside window
- file truncated before requested window
- metadata-only delta with no ops
- file changed with visible bytes unchanged

For each case:

1. Build old file bytes.
2. Build requested old window.
3. Apply file or window change.
4. Generate snapshot/delta/reset.
5. Apply with Python reassembler.
6. Assert reassembled window bytes equal direct projection from changed file.
7. Decode only after byte equality is proven.

### Phase P5: async FileConnection and FileWindowSubscription

Tests:

- open emits snapshot
- file_changed emits deltas to subscribers
- update_window grows/shrinks without calling file_changed
- two subscribers with different windows maintain independent seq/windowVersion
- close emits stop event
- deleted file emits `on_error(code="deleted")` and closes
- consumer failure closes/reopens in harness

Use temporary files. Do not import watchdog or service code.

### Phase P6: randomized fixture tests

Use deterministic random generation, with no dependency required initially:

- random initial text
- random line windows
- random edits: line replace, insert, delete, truncate, append
- random window grow/shrink/move
- assert reassembled output equals direct projection at each step

If dependency policy allows and the project owner approves, add Hypothesis later.

## TypeScript Test Plan

TypeScript tests prove browser-side reassembly. They should use payload fixtures
generated by Python plus hand-written edge cases for validation failures.

### TS structures and validators

Tests:

- valid full snapshot parses
- valid text-window snapshot parses
- valid text-window delta parses
- malformed op rejected
- unknown codec rejected unless explicitly supported
- invalid base64 rejected

### TS reassembler tests

For each Python fixture:

1. Load JSON event stream.
2. Apply snapshots/deltas/resets with TS reassembler to `Uint8Array`.
3. Decode after apply.
4. Assert final bytes and final text match expected output.

Required fixture scenarios:

- start
- reset
- grow
- shrink
- lines changed
- lines inserted
- lines removed
- file truncated
- CRLF
- UTF-8 multibyte
- metadata-only delta

### Cross-language golden fixtures

Python writes fixture streams under a test fixture directory. TypeScript consumes
the same fixtures.

Example fixture shape:

```text
fixtures/window_cases/
  grow-prefix/
    events.jsonl
    expected-window.bin
    expected-window.txt
  truncate-inside/
    events.jsonl
    expected-window.bin
    expected-window.txt
```

No absolute paths in fixtures.

## Roll-Build Phases

### Phase 0: dependency and codec spike

Goal:

- Confirm structured ops remain v1.
- Verify no VCDIFF dependency is needed for phase 1.
- Optionally run a small benchmark comparing structured ops payload size to
  window reset size.

Deliverables:

- short note in the plan or design doc
- no production dependency changes unless explicitly approved

Exit criteria:

- documented codec decision
- no unresolved dependency blocker

### Phase 1: Python model and byte-op core

Deliverables:

- `services/filedelta/pyproject.toml`
- `services/filedelta/src/filedelta/` package skeleton
- Python model types
- byte op apply/diff primitives
- validation errors
- focused tests

Exit criteria:

- focused tests pass
- no grip-lab service imports in `filedelta`

### Phase 2: Python full snapshots and text-window snapshots

Deliverables:

- full snapshot generation/apply
- line index
- text-window projection
- reset model

Exit criteria:

- line/window fixture tests pass
- CRLF and UTF-8 cases pass

### Phase 3: Python text-window delta generation

Deliverables:

- grow/shrink/window-change delta generation
- file-change reprojection
- metadata-only deltas
- truncation handling

Exit criteria:

- required Python scenarios pass
- deterministic random reassembly tests pass

### Phase 4: TypeScript reassembler

Deliverables:

- TS model interfaces and runtime validation
- `Uint8Array` byte-op apply
- window reassembler

Exit criteria:

- TS tests pass against hand-written fixtures

### Phase 5: cross-language fixtures

Deliverables:

- Python-generated JSONL fixture streams
- TS consumes fixtures and verifies exact bytes/text
- fixture generation command, e.g. `uv run python -m filedelta.testing.gen_fixtures`

Exit criteria:

- all required cross-language scenarios pass
- fixture update workflow documented

### Phase 6: async connection/window runtime

Deliverables:

- `FileConnection`
- `FileWindowSubscription`
- subscriber callback tests
- temp-file based lifecycle tests

Exit criteria:

- async tests pass
- multiple subscribers behave independently

### Phase 7: package polish

Deliverables:

- package metadata
- public API exports
- README or usage examples
- type-check/lint/test commands documented

Exit criteria:

- clean package test run
- ready for service integration plan

## Roll-Build Guardrails

Pause before continuing if:

- structured ops cannot meet basic performance expectations for normal editor
  windows
- TS and Python disagree on any fixture interpretation
- window reprojection semantics become ambiguous under insert/delete-before-window
- dependency changes are needed and publish dates have not been checked
- the phase requires service integration before the pure library is stable

## Planning Status

Ready for roll-build planning. I recommend starting with Phase 0 only if the
VCDIFF question is still contentious; otherwise start at Phase 1 and keep the
codec hook in the model.

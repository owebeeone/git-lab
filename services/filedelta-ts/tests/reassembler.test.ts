import {
  TextWindowReassembler,
  applyOps,
  parseFullSnapshot,
  parseTextWindowDelta,
  parseTextWindowSnapshot,
} from "../src/index.js";
import type { ResetEvent } from "../src/index.js";

function assert(condition: unknown, message: string): void {
  if (!condition) throw new Error(message);
}

function assertThrows(fn: () => void, message: string): void {
  let threw = false;
  try {
    fn();
  } catch {
    threw = true;
  }
  assert(threw, message);
}

function bytes(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

function sameBytes(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false;
  return left.every((value, index) => value === right[index]);
}

const fullSnapshotJson = {
  scope: "full",
  resourceId: "file:full",
  fileVersion: "fv000001",
  contentHash: "sha256:full",
  kind: "content",
  size: 6,
  data: "base64:YWxwaGEK",
  metadata: {},
};

const textSnapshotJson = {
  scope: "text-window",
  resourceId: "file:window",
  windowId: "win:window",
  fileVersion: "fv000001",
  windowVersion: "wv000001",
  contentHash: "sha256:alpha",
  kind: "content",
  lineStart: 0,
  lineEnd: 1,
  totalLines: 2,
  startByte: 0,
  endByte: 6,
  lineIndex: [0],
  truncated: false,
  size: 6,
  data: "base64:YWxwaGEK",
  metadata: {},
};

const textDeltaJson = {
  scope: "text-window",
  resourceId: "file:window",
  windowId: "win:window",
  seq: 1,
  reason: "window-grow",
  baseFileVersion: "fv000001",
  resultFileVersion: "fv000001",
  baseWindowVersion: "wv000001",
  resultWindowVersion: "wv000002",
  baseHash: "sha256:alpha",
  resultHash: "sha256:alphabeta",
  lineStart: 0,
  lineEnd: 2,
  totalLines: 2,
  startByte: 0,
  endByte: 11,
  lineIndex: [0, 6],
  truncated: false,
  resultSize: 11,
  codec: { name: "structured-byte-ops", version: 1 },
  ops: [{ op: "insert", offset: 6, data: "base64:YmV0YQo=" }],
  metadata: {},
  kind: "content",
};

function testValidators(): void {
  assert(sameBytes(parseFullSnapshot(fullSnapshotJson).data, bytes("alpha\n")), "full snapshot parses");
  assert(
    sameBytes(parseTextWindowSnapshot(textSnapshotJson).data, bytes("alpha\n")),
    "text snapshot parses",
  );
  assert(parseTextWindowDelta(textDeltaJson).ops.length === 1, "text delta parses");
  assertThrows(
    () => parseTextWindowDelta({ ...textDeltaJson, ops: [{ op: "copy", offset: 0 }] }),
    "malformed op rejected",
  );
  assertThrows(
    () => parseTextWindowDelta({ ...textDeltaJson, codec: { name: "vcdiff", version: 1 } }),
    "unknown codec rejected",
  );
  assertThrows(
    () => parseTextWindowSnapshot({ ...textSnapshotJson, data: "base64:not valid" }),
    "invalid base64 rejected",
  );
}

function testApplyOps(): void {
  const result = applyOps(bytes("alpha\ngamma\n"), [
    { op: "insert", offset: 6, length: 0, data: bytes("beta\n") },
  ]);
  assert(sameBytes(result, bytes("alpha\nbeta\ngamma\n")), "insert op applies");
}

function testReassemblerDelta(): void {
  const reassembler = new TextWindowReassembler();
  reassembler.applySnapshot(parseTextWindowSnapshot(textSnapshotJson));
  reassembler.applyDelta(parseTextWindowDelta(textDeltaJson));
  assert(reassembler.text === "alpha\nbeta\n", "delta reassembles text");
}

function testReassemblerReset(): void {
  const reassembler = new TextWindowReassembler();
  reassembler.applySnapshot(parseTextWindowSnapshot(textSnapshotJson));
  const reset: ResetEvent = {
    type: "reset",
    reason: "window-move",
    seq: 1,
    snapshot: parseTextWindowSnapshot({
      ...textSnapshotJson,
      fileVersion: "fv000002",
      windowVersion: "wv000002",
      contentHash: "sha256:gamma",
      lineStart: 2,
      lineEnd: 3,
      startByte: 11,
      endByte: 17,
      data: "base64:Z2FtbWEK",
      size: 6,
    }),
  };
  reassembler.applyReset(reset);
  assert(reassembler.text === "gamma\n", "reset replaces text");
}

function testSeqValidation(): void {
  const reassembler = new TextWindowReassembler();
  reassembler.applySnapshot(parseTextWindowSnapshot(textSnapshotJson));
  assertThrows(
    () => reassembler.applyDelta(parseTextWindowDelta({ ...textDeltaJson, seq: 2 })),
    "non-contiguous seq rejected",
  );
}

testValidators();
testApplyOps();
testReassemblerDelta();
testReassemblerReset();
testSeqValidation();

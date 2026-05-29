import type { ByteOp } from "./model.js";

export function applyOps(data: Uint8Array, ops: ByteOp[]): Uint8Array {
  validateNonOverlappingRanges(ops);
  let result = data;
  for (const op of ops) {
    if (op.offset > result.length) {
      throw new Error("offset is beyond end of buffer");
    }
    if (op.op === "insert") {
      result = concat(result.slice(0, op.offset), op.data, result.slice(op.offset));
      continue;
    }

    const end = op.offset + op.length;
    if (end > result.length) {
      throw new Error("op range is beyond end of buffer");
    }
    if (op.op === "delete") {
      result = concat(result.slice(0, op.offset), result.slice(end));
    } else {
      result = concat(result.slice(0, op.offset), op.data, result.slice(end));
    }
  }
  return result;
}

function validateNonOverlappingRanges(ops: ByteOp[]): void {
  const ranges = ops
    .filter((op) => op.op !== "insert")
    .map((op) => [op.offset, op.offset + op.length] as const)
    .sort((left, right) => left[0] - right[0]);
  for (let index = 1; index < ranges.length; index += 1) {
    if (ranges[index][0] < ranges[index - 1][1]) {
      throw new Error("ops must not overlap");
    }
  }
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const length = parts.reduce((total, part) => total + part.length, 0);
  const result = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    result.set(part, offset);
    offset += part.length;
  }
  return result;
}

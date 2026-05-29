import { decodeBase64Payload } from "./base64.js";

export interface CodecDescriptor {
  name: "structured-byte-ops";
  version: 1;
}

export interface ByteOp {
  op: "insert" | "delete" | "replace";
  offset: number;
  length: number;
  data: Uint8Array;
}

export interface FullSnapshot {
  scope: "full";
  resourceId: string;
  fileVersion: string;
  contentHash: string;
  kind: string;
  size: number;
  data: Uint8Array;
  metadata: Record<string, unknown>;
}

export interface TextWindowSnapshot {
  scope: "text-window";
  resourceId: string;
  windowId: string;
  fileVersion: string;
  windowVersion: string;
  contentHash: string;
  kind: string;
  lineStart: number;
  lineEnd: number;
  totalLines: number;
  startByte: number;
  endByte: number;
  lineIndex: number[];
  truncated: boolean;
  size: number;
  data: Uint8Array;
  metadata: Record<string, unknown>;
}

export interface TextWindowDelta {
  scope: "text-window";
  resourceId: string;
  windowId: string;
  seq: number;
  reason: string;
  baseFileVersion: string;
  resultFileVersion: string;
  baseWindowVersion: string;
  resultWindowVersion: string;
  baseHash: string;
  resultHash: string;
  lineStart: number;
  lineEnd: number;
  totalLines: number;
  startByte: number;
  endByte: number;
  lineIndex: number[];
  truncated: boolean;
  resultSize: number;
  codec: CodecDescriptor;
  ops: ByteOp[];
  metadata: Record<string, unknown>;
  kind: string;
}

export interface ResetEvent {
  type: "reset";
  reason: string;
  seq: number;
  snapshot: TextWindowSnapshot;
}

type JsonObject = Record<string, unknown>;

function asObject(value: unknown, name: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${name} must be an object`);
  }
  return value as JsonObject;
}

function asString(value: unknown, name: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${name} must be a non-empty string`);
  }
  return value;
}

function asNumber(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${name} must be a non-negative integer`);
  }
  return value;
}

function asBoolean(value: unknown, name: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${name} must be a boolean`);
  }
  return value;
}

function asNumberArray(value: unknown, name: string): number[] {
  if (!Array.isArray(value)) {
    throw new Error(`${name} must be an array`);
  }
  return value.map((item, index) => asNumber(item, `${name}[${index}]`));
}

function asMetadata(value: unknown): Record<string, unknown> {
  if (value === undefined) return {};
  return asObject(value, "metadata");
}

export function parseCodec(value: unknown): CodecDescriptor {
  const object = asObject(value, "codec");
  if (object.name !== "structured-byte-ops" || object.version !== 1) {
    throw new Error("unsupported codec");
  }
  return { name: "structured-byte-ops", version: 1 };
}

export function parseByteOp(value: unknown): ByteOp {
  const object = asObject(value, "op");
  const op = asString(object.op, "op.op");
  if (op !== "insert" && op !== "delete" && op !== "replace") {
    throw new Error("unknown op");
  }
  const offset = asNumber(object.offset, "op.offset");
  const length = op === "insert" ? 0 : asNumber(object.length, "op.length");
  const data = op === "delete" ? new Uint8Array() : decodeBase64Payload(object.data);
  if (op === "insert" && object.length !== undefined && object.length !== 0) {
    throw new Error("insert length must be zero");
  }
  if ((op === "delete" || op === "replace") && length <= 0) {
    throw new Error("delete/replace length must be positive");
  }
  if ((op === "insert" || op === "replace") && data.length === 0) {
    throw new Error("insert/replace data must not be empty");
  }
  return { op, offset, length, data };
}

export function parseFullSnapshot(value: unknown): FullSnapshot {
  const object = asObject(value, "snapshot");
  if (object.scope !== "full") throw new Error("snapshot scope must be full");
  const data = decodeBase64Payload(object.data);
  const size = asNumber(object.size, "size");
  if (size !== data.length) throw new Error("snapshot size mismatch");
  return {
    scope: "full",
    resourceId: asString(object.resourceId, "resourceId"),
    fileVersion: asString(object.fileVersion, "fileVersion"),
    contentHash: asString(object.contentHash, "contentHash"),
    kind: asString(object.kind, "kind"),
    size,
    data,
    metadata: asMetadata(object.metadata),
  };
}

export function parseTextWindowSnapshot(value: unknown): TextWindowSnapshot {
  const object = asObject(value, "snapshot");
  if (object.scope !== "text-window") throw new Error("snapshot scope must be text-window");
  const data = decodeBase64Payload(object.data);
  const size = asNumber(object.size, "size");
  if (size !== data.length) throw new Error("snapshot size mismatch");
  return {
    scope: "text-window",
    resourceId: asString(object.resourceId, "resourceId"),
    windowId: asString(object.windowId, "windowId"),
    fileVersion: asString(object.fileVersion, "fileVersion"),
    windowVersion: asString(object.windowVersion, "windowVersion"),
    contentHash: asString(object.contentHash, "contentHash"),
    kind: asString(object.kind, "kind"),
    lineStart: asNumber(object.lineStart, "lineStart"),
    lineEnd: asNumber(object.lineEnd, "lineEnd"),
    totalLines: asNumber(object.totalLines, "totalLines"),
    startByte: asNumber(object.startByte, "startByte"),
    endByte: asNumber(object.endByte, "endByte"),
    lineIndex: asNumberArray(object.lineIndex, "lineIndex"),
    truncated: asBoolean(object.truncated, "truncated"),
    size,
    data,
    metadata: asMetadata(object.metadata),
  };
}

export function parseTextWindowDelta(value: unknown): TextWindowDelta {
  const object = asObject(value, "delta");
  if (object.scope !== "text-window") throw new Error("delta scope must be text-window");
  const opsValue = object.ops;
  if (!Array.isArray(opsValue)) throw new Error("ops must be an array");
  return {
    scope: "text-window",
    resourceId: asString(object.resourceId, "resourceId"),
    windowId: asString(object.windowId, "windowId"),
    seq: asNumber(object.seq, "seq"),
    reason: asString(object.reason, "reason"),
    baseFileVersion: asString(object.baseFileVersion, "baseFileVersion"),
    resultFileVersion: asString(object.resultFileVersion, "resultFileVersion"),
    baseWindowVersion: asString(object.baseWindowVersion, "baseWindowVersion"),
    resultWindowVersion: asString(object.resultWindowVersion, "resultWindowVersion"),
    baseHash: asString(object.baseHash, "baseHash"),
    resultHash: asString(object.resultHash, "resultHash"),
    lineStart: asNumber(object.lineStart, "lineStart"),
    lineEnd: asNumber(object.lineEnd, "lineEnd"),
    totalLines: asNumber(object.totalLines, "totalLines"),
    startByte: asNumber(object.startByte, "startByte"),
    endByte: asNumber(object.endByte, "endByte"),
    lineIndex: asNumberArray(object.lineIndex, "lineIndex"),
    truncated: asBoolean(object.truncated, "truncated"),
    resultSize: asNumber(object.resultSize, "resultSize"),
    codec: parseCodec(object.codec),
    ops: opsValue.map(parseByteOp),
    metadata: asMetadata(object.metadata),
    kind: typeof object.kind === "string" ? object.kind : "content",
  };
}

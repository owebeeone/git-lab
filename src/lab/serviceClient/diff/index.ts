export const DIFF_CONTENT_TYPE = 'application/vnd.griplab.diff+json;version=1';

export type DiffRefKind = 'working' | 'head';
export type DiffLineKind = 'same' | 'add' | 'del' | 'change';
export type DiffDiagnosticCode =
  | 'missing-file'
  | 'binary-file'
  | 'decode-failed'
  | 'window-truncated'
  | 'peer-offline'
  | 'unsupported-ref';

export interface DiffRef {
  kind: DiffRefKind;
}

export interface DiffEndpoint {
  peerId: string;
  repoPath: string;
  path: string;
  ref: DiffRef;
}

export interface DiffSourceState extends DiffEndpoint {
  fileVersion: string;
  contentHash: string;
}

export interface DiffWindow {
  lineStart: number;
  lineEnd: number;
  truncated: boolean;
}

export interface DiffLine {
  kind: DiffLineKind;
  leftNo: number | null;
  rightNo: number | null;
  left: string | null;
  right: string | null;
}

export interface DiffHunk {
  id: string;
  leftStart: number;
  leftLines: number;
  rightStart: number;
  rightLines: number;
  lines: DiffLine[];
}

export interface DiffDiagnostic {
  code: DiffDiagnosticCode;
  message: string;
  endpoint: 'left' | 'right' | null;
  details: Record<string, unknown>;
}

export interface DiffPayload {
  contentType: typeof DIFF_CONTENT_TYPE;
  diffId: string;
  version: string;
  left: DiffSourceState;
  right: DiffSourceState;
  window: DiffWindow;
  hunks: DiffHunk[];
  unifiedText: string | null;
  diagnostics: DiffDiagnostic[];
}

export function parseDiffPayload(value: unknown): DiffPayload {
  const obj = objectValue(value, 'diff payload');
  const payload: DiffPayload = {
    contentType: literal(obj.contentType, DIFF_CONTENT_TYPE, 'contentType'),
    diffId: stringValue(obj.diffId, 'diffId'),
    version: stringValue(obj.version, 'version'),
    left: parseSourceState(obj.left, 'left'),
    right: parseSourceState(obj.right, 'right'),
    window: parseWindow(obj.window),
    hunks: arrayValue(obj.hunks, 'hunks').map(parseHunk),
    unifiedText: nullableString(obj.unifiedText, 'unifiedText'),
    diagnostics: arrayValue(obj.diagnostics, 'diagnostics').map(parseDiagnostic),
  };
  if (!payload.diffId.startsWith('diff-')) throw new Error('diffId must use diff- prefix');
  if (!payload.version.startsWith('dv')) throw new Error('version must use dv prefix');
  return payload;
}

function parseSourceState(value: unknown, label: string): DiffSourceState {
  const endpoint = parseEndpoint(value, label);
  const obj = objectValue(value, label);
  return {
    ...endpoint,
    fileVersion: stringValue(obj.fileVersion, `${label}.fileVersion`),
    contentHash: stringValue(obj.contentHash, `${label}.contentHash`),
  };
}

function parseEndpoint(value: unknown, label: string): DiffEndpoint {
  const obj = objectValue(value, label);
  return {
    peerId: stringValue(obj.peerId, `${label}.peerId`),
    repoPath: stringValue(obj.repoPath, `${label}.repoPath`, { allowEmpty: true }),
    path: stringValue(obj.path, `${label}.path`),
    ref: parseRef(obj.ref, `${label}.ref`),
  };
}

function parseRef(value: unknown, label: string): DiffRef {
  const obj = objectValue(value, label);
  const kind = literalOneOf(obj.kind, ['working', 'head'], `${label}.kind`);
  return { kind };
}

function parseWindow(value: unknown): DiffWindow {
  const obj = objectValue(value, 'window');
  const lineStart = numberValue(obj.lineStart, 'window.lineStart');
  const lineEnd = numberValue(obj.lineEnd, 'window.lineEnd');
  if (lineStart < 0) throw new Error('window.lineStart must be non-negative');
  if (lineEnd < lineStart) throw new Error('window.lineEnd must be >= window.lineStart');
  return {
    lineStart,
    lineEnd,
    truncated: booleanValue(obj.truncated, 'window.truncated'),
  };
}

function parseHunk(value: unknown): DiffHunk {
  const obj = objectValue(value, 'hunk');
  return {
    id: stringValue(obj.id, 'hunk.id'),
    leftStart: oneBased(obj.leftStart, 'hunk.leftStart'),
    leftLines: nonNegative(obj.leftLines, 'hunk.leftLines'),
    rightStart: oneBased(obj.rightStart, 'hunk.rightStart'),
    rightLines: nonNegative(obj.rightLines, 'hunk.rightLines'),
    lines: arrayValue(obj.lines, 'hunk.lines').map(parseLine),
  };
}

function parseLine(value: unknown): DiffLine {
  const obj = objectValue(value, 'line');
  const kind = literalOneOf(obj.kind, ['same', 'add', 'del', 'change'], 'line.kind');
  const line: DiffLine = {
    kind,
    leftNo: nullableOneBased(obj.leftNo, 'line.leftNo'),
    rightNo: nullableOneBased(obj.rightNo, 'line.rightNo'),
    left: nullableString(obj.left, 'line.left'),
    right: nullableString(obj.right, 'line.right'),
  };
  if ((kind === 'same' || kind === 'change') && (line.leftNo == null || line.rightNo == null || line.left == null || line.right == null)) {
    throw new Error(`${kind} line requires both sides`);
  }
  if (kind === 'add' && (line.leftNo != null || line.left != null || line.rightNo == null || line.right == null)) {
    throw new Error('add line shape is invalid');
  }
  if (kind === 'del' && (line.rightNo != null || line.right != null || line.leftNo == null || line.left == null)) {
    throw new Error('del line shape is invalid');
  }
  return line;
}

function parseDiagnostic(value: unknown): DiffDiagnostic {
  const obj = objectValue(value, 'diagnostic');
  return {
    code: literalOneOf(
      obj.code,
      ['missing-file', 'binary-file', 'decode-failed', 'window-truncated', 'peer-offline', 'unsupported-ref'],
      'diagnostic.code',
    ),
    message: stringValue(obj.message, 'diagnostic.message'),
    endpoint: nullableOneOf(obj.endpoint, ['left', 'right'], 'diagnostic.endpoint'),
    details: objectValue(obj.details, 'diagnostic.details'),
  };
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error(`${label} must be an object`);
  return value as Record<string, unknown>;
}

function arrayValue(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value;
}

function stringValue(value: unknown, label: string, opts: { allowEmpty?: boolean } = {}): string {
  if (typeof value !== 'string') throw new Error(`${label} must be a string`);
  if (!opts.allowEmpty && value.length === 0) throw new Error(`${label} must be a non-empty string`);
  return value;
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  return stringValue(value, label, { allowEmpty: true });
}

function numberValue(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value)) throw new Error(`${label} must be an integer`);
  return value;
}

function booleanValue(value: unknown, label: string): boolean {
  if (typeof value !== 'boolean') throw new Error(`${label} must be a boolean`);
  return value;
}

function literal<T extends string>(value: unknown, expected: T, label: string): T {
  if (value !== expected) throw new Error(`${label} must be ${expected}`);
  return expected;
}

function literalOneOf<const T extends readonly string[]>(value: unknown, allowed: T, label: string): T[number] {
  if (typeof value !== 'string' || !allowed.includes(value)) throw new Error(`${label} is invalid`);
  return value as T[number];
}

function nullableOneOf<const T extends readonly string[]>(value: unknown, allowed: T, label: string): T[number] | null {
  if (value === null) return null;
  return literalOneOf(value, allowed, label);
}

function nonNegative(value: unknown, label: string): number {
  const n = numberValue(value, label);
  if (n < 0) throw new Error(`${label} must be non-negative`);
  return n;
}

function oneBased(value: unknown, label: string): number {
  const n = numberValue(value, label);
  if (n < 1) throw new Error(`${label} must be one-based`);
  return n;
}

function nullableOneBased(value: unknown, label: string): number | null {
  if (value === null) return null;
  return oneBased(value, label);
}

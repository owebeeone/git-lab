export type ProtocolKind = 'request' | 'response' | 'stream-event' | 'error';

export interface ServiceErrorInfo {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export interface ServiceStreamEvent {
  streamId: string;
  seq: number;
  event: string;
  payload: Record<string, unknown>;
}

export interface ServiceEnvelope {
  messageId: string;
  kind: ProtocolKind;
  method?: string;
  streamId?: string;
  payload: Record<string, unknown>;
  error?: ServiceErrorInfo;
}

export type PeerPresenceStatus = 'configured' | 'offline' | 'bootstrapping' | 'starting' | 'online' | 'error';

export interface PeerPresence {
  id: string;
  name: string;
  sshAddress: string;
  location: string;
  os: 'macos' | 'linux' | 'windows' | null;
  shells: string[];
  online: boolean;
  isSelf: boolean;
  status: PeerPresenceStatus;
  summary: string;
  lastSeenAt: number | null;
}

export interface PeerPresencePayload {
  peers: PeerPresence[];
}

export interface PeerHealthCheck {
  id: string;
  status: 'ok' | 'pending' | 'error';
  summary: string;
}

export interface PeerHealth {
  peerId: string;
  status: PeerPresenceStatus;
  summary: string;
  checks: PeerHealthCheck[];
  updatedAt: number;
}

export class ServiceProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ServiceProtocolError';
  }
}

const protocolKinds = new Set<ProtocolKind>(['request', 'response', 'stream-event', 'error']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireString(value: Record<string, unknown>, key: string): string {
  const result = value[key];
  if (typeof result !== 'string' || result.length === 0) {
    throw new ServiceProtocolError(`${key} must be a non-empty string`);
  }
  return result;
}

function optionalString(value: Record<string, unknown>, key: string): string | undefined {
  const result = value[key];
  if (result === undefined) return undefined;
  if (typeof result !== 'string' || result.length === 0) {
    throw new ServiceProtocolError(`${key} must be a non-empty string when present`);
  }
  return result;
}

function optionalPayload(value: Record<string, unknown>, key: string): Record<string, unknown> {
  const result = value[key];
  if (result === undefined) return {};
  if (!isRecord(result)) {
    throw new ServiceProtocolError(`${key} must be an object`);
  }
  return result;
}

function optionalNullableString(value: Record<string, unknown>, key: string): string | null {
  const result = value[key];
  if (result === undefined || result === null) return null;
  if (typeof result !== 'string') {
    throw new ServiceProtocolError(`${key} must be a string or null`);
  }
  return result;
}

function optionalBoolean(value: Record<string, unknown>, key: string, fallback: boolean): boolean {
  const result = value[key];
  if (result === undefined) return fallback;
  if (typeof result !== 'boolean') {
    throw new ServiceProtocolError(`${key} must be a boolean`);
  }
  return result;
}

function optionalNumberOrNull(value: Record<string, unknown>, key: string): number | null {
  const result = value[key];
  if (result === undefined || result === null) return null;
  if (typeof result !== 'number' || !Number.isFinite(result)) {
    throw new ServiceProtocolError(`${key} must be a finite number or null`);
  }
  return result;
}

function optionalStringArray(value: Record<string, unknown>, key: string): string[] {
  const result = value[key];
  if (result === undefined) return [];
  if (!Array.isArray(result) || !result.every((item) => typeof item === 'string')) {
    throw new ServiceProtocolError(`${key} must be an array of strings`);
  }
  return result;
}

const peerPresenceStatuses = new Set<PeerPresenceStatus>([
  'configured',
  'offline',
  'bootstrapping',
  'starting',
  'online',
  'error',
]);

function optionalPeerPresenceStatus(value: Record<string, unknown>): PeerPresenceStatus {
  const raw = value.status;
  if (raw === undefined) return optionalBoolean(value, 'online', false) ? 'online' : 'configured';
  if (typeof raw !== 'string' || !peerPresenceStatuses.has(raw as PeerPresenceStatus)) {
    throw new ServiceProtocolError('peer status must be a known presence status');
  }
  return raw as PeerPresenceStatus;
}

function parsePeerPresence(value: unknown): PeerPresence {
  if (!isRecord(value)) {
    throw new ServiceProtocolError('peer presence must be an object');
  }
  const id = requireString(value, 'id');
  const online = optionalBoolean(value, 'online', false);
  const status = optionalPeerPresenceStatus(value);
  const os = optionalNullableString(value, 'os');
  if (os !== null && os !== 'macos' && os !== 'linux' && os !== 'windows') {
    throw new ServiceProtocolError('peer os must be macos, linux, windows, or null');
  }
  return {
    id,
    name: optionalString(value, 'name') ?? id,
    sshAddress: optionalNullableString(value, 'sshAddress') ?? '',
    location: optionalNullableString(value, 'location') ?? '',
    os,
    shells: optionalStringArray(value, 'shells'),
    online,
    isSelf: optionalBoolean(value, 'isSelf', false),
    status,
    summary: optionalNullableString(value, 'summary') ?? '',
    lastSeenAt: optionalNumberOrNull(value, 'lastSeenAt'),
  };
}

export function parsePeerPresencePayload(value: unknown): PeerPresencePayload {
  if (!isRecord(value)) {
    throw new ServiceProtocolError('peer presence payload must be an object');
  }
  const peers = value.peers;
  if (!Array.isArray(peers)) {
    throw new ServiceProtocolError('peers must be an array');
  }
  return { peers: peers.map(parsePeerPresence) };
}

function parsePeerHealthCheck(value: unknown): PeerHealthCheck {
  if (!isRecord(value)) {
    throw new ServiceProtocolError('peer health check must be an object');
  }
  const status = requireString(value, 'status');
  if (status !== 'ok' && status !== 'pending' && status !== 'error') {
    throw new ServiceProtocolError('peer health check status must be ok, pending, or error');
  }
  return {
    id: requireString(value, 'id'),
    status,
    summary: optionalNullableString(value, 'summary') ?? '',
  };
}

export function parsePeerHealth(value: unknown): PeerHealth {
  if (!isRecord(value)) {
    throw new ServiceProtocolError('peer health must be an object');
  }
  const checks = value.checks;
  if (!Array.isArray(checks)) {
    throw new ServiceProtocolError('peer health checks must be an array');
  }
  const updatedAt = value.updatedAt;
  if (typeof updatedAt !== 'number' || !Number.isFinite(updatedAt)) {
    throw new ServiceProtocolError('peer health updatedAt must be a finite number');
  }
  return {
    peerId: requireString(value, 'peerId'),
    status: optionalPeerPresenceStatus(value),
    summary: optionalNullableString(value, 'summary') ?? '',
    checks: checks.map(parsePeerHealthCheck),
    updatedAt,
  };
}

export function parseServiceErrorInfo(value: unknown): ServiceErrorInfo {
  if (!isRecord(value)) {
    throw new ServiceProtocolError('error must be an object');
  }
  return {
    code: requireString(value, 'code'),
    message: requireString(value, 'message'),
    details: optionalPayload(value, 'details'),
  };
}

export function parseServiceStreamEvent(value: unknown): ServiceStreamEvent {
  if (!isRecord(value)) {
    throw new ServiceProtocolError('stream event must be an object');
  }
  const seq = value.seq;
  if (typeof seq !== 'number' || !Number.isInteger(seq) || seq < 0) {
    throw new ServiceProtocolError('seq must be a non-negative integer');
  }
  return {
    streamId: requireString(value, 'streamId'),
    seq,
    event: requireString(value, 'event'),
    payload: optionalPayload(value, 'payload'),
  };
}

export function parseServiceEnvelope(value: unknown): ServiceEnvelope {
  if (!isRecord(value)) {
    throw new ServiceProtocolError('envelope must be an object');
  }

  const kind = requireString(value, 'kind') as ProtocolKind;
  if (!protocolKinds.has(kind)) {
    throw new ServiceProtocolError(`unsupported message kind: ${kind}`);
  }

  const method = optionalString(value, 'method');
  if ((kind === 'request' || kind === 'response' || kind === 'stream-event') && !method) {
    throw new ServiceProtocolError(`${kind} envelope requires method`);
  }

  const streamId = optionalString(value, 'streamId');
  if (kind === 'stream-event' && !streamId) {
    throw new ServiceProtocolError('stream-event envelope requires streamId');
  }

  const errorValue = value.error;
  if (kind === 'error') {
    if (errorValue === undefined) {
      throw new ServiceProtocolError('error envelope requires error');
    }
  } else if (errorValue !== undefined) {
    throw new ServiceProtocolError('non-error envelope must not include error');
  }

  return {
    messageId: requireString(value, 'messageId'),
    kind,
    ...(method ? { method } : {}),
    ...(streamId ? { streamId } : {}),
    payload: optionalPayload(value, 'payload'),
    ...(errorValue !== undefined ? { error: parseServiceErrorInfo(errorValue) } : {}),
  };
}

export function encodeServiceEnvelope(envelope: ServiceEnvelope): Record<string, unknown> {
  return parseServiceEnvelope(envelope) as unknown as Record<string, unknown>;
}

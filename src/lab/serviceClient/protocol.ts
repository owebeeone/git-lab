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

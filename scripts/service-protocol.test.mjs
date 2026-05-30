import assert from 'node:assert/strict';
import {
  ServiceProtocolError,
  encodeServiceEnvelope,
  parseServiceEnvelope,
  parseServiceStreamEvent,
} from '../src/lab/serviceClient/protocol.ts';

const request = {
  messageId: 'm000001',
  kind: 'request',
  method: 'workspace.status.subscribe',
  payload: { root: '.' },
};
assert.deepEqual(parseServiceEnvelope(encodeServiceEnvelope(request)), request);

const streamEvent = {
  streamId: 's000001',
  seq: 2,
  event: 'snapshot',
  payload: { repos: [] },
};
const streamEnvelope = {
  messageId: 'm000002',
  kind: 'stream-event',
  method: 'workspace.status.subscribe',
  streamId: 's000001',
  payload: streamEvent,
};
assert.deepEqual(parseServiceEnvelope(streamEnvelope), streamEnvelope);
assert.deepEqual(parseServiceStreamEvent(streamEnvelope.payload), streamEvent);

const errorEnvelope = {
  messageId: 'm000003',
  kind: 'error',
  method: 'file.subscribe',
  payload: {},
  error: { code: 'not-found', message: 'file does not exist', details: { path: 'missing.py' } },
};
assert.deepEqual(parseServiceEnvelope(errorEnvelope), errorEnvelope);

assert.throws(
  () => parseServiceEnvelope({ ...request, kind: 'unknown' }),
  ServiceProtocolError,
);
assert.throws(
  () => parseServiceEnvelope({ ...streamEnvelope, streamId: undefined }),
  /streamId/,
);

console.log('OK: service protocol validators');

import assert from 'node:assert/strict';
import {
  ServiceClient,
} from '../src/lab/serviceClient/client.ts';
import {
  FakeServiceTransport,
} from '../src/lab/serviceClient/fakeTransport.ts';
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

const transport = new FakeServiceTransport();
const client = new ServiceClient({ url: 'ws://test.local/ws', transportFactory: () => transport });
const requestPromise = client.request('health.get', { ok: true });
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(transport.sent.length, 1);
assert.equal(transport.sent[0].messageId, 'm000001');
transport.push({
  messageId: 'm000001',
  kind: 'response',
  method: 'health.get',
  payload: { ok: true },
});
assert.deepEqual((await requestPromise).payload, { ok: true });
assert.equal(client.httpUrl, 'http://test.local/');

const streamIterator = client.subscribe('workspace.status.subscribe')[Symbol.asyncIterator]();
const nextWorkspaceEvent = streamIterator.next();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(transport.sent.length, 2);
assert.equal(transport.sent[1].method, 'workspace.status.subscribe');
assert.equal(transport.sent[1].streamId, 's000001');
transport.push({
  messageId: transport.sent[1].messageId,
  kind: 'stream-event',
  method: 'workspace.status.subscribe',
  streamId: 's000001',
  payload: {
    streamId: 's000001',
    seq: 1,
    event: 'snapshot',
    payload: { repos: [{ path: '', name: 'repo' }] },
  },
});
const workspaceStreamEvent = await nextWorkspaceEvent;
assert.equal(workspaceStreamEvent.value.event, 'snapshot');
assert.deepEqual(workspaceStreamEvent.value.payload, { repos: [{ path: '', name: 'repo' }] });

const controller = new AbortController();
const statusIterator = client.watchStatus(controller.signal)[Symbol.asyncIterator]();
assert.equal((await statusIterator.next()).value.status, 'connected');
const disconnectedStatus = statusIterator.next();
client.close();
assert.equal((await disconnectedStatus).value.status, 'disconnected');
controller.abort();

const closedTransport = new FakeServiceTransport();
const closedClient = new ServiceClient({ url: 'ws://test.local/ws', transportFactory: () => closedTransport });
await closedClient.connect();
const reconnecting = closedClient.watchStatus()[Symbol.asyncIterator]();
assert.equal((await reconnecting.next()).value.status, 'connected');
const reconnectingStatus = reconnecting.next();
closedTransport.close();
assert.equal((await reconnectingStatus).value.status, 'reconnecting');

console.log('OK: service protocol validators');

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  ServiceClient,
} from '../src/lab/serviceClient/client.ts';
import {
  parseDiffPayload,
} from '../src/lab/serviceClient/diff/index.ts';
import {
  FakeServiceTransport,
} from '../src/lab/serviceClient/fakeTransport.ts';
import {
  ServiceProtocolError,
  encodeServiceEnvelope,
  parsePeerHealth,
  parsePeerPresencePayload,
  parseServiceEnvelope,
  parseServiceStreamEvent,
} from '../src/lab/serviceClient/protocol.ts';

const here = dirname(fileURLToPath(import.meta.url));

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

for (const fixture of ['empty_same.json', 'diagnostics.json']) {
  const value = JSON.parse(readFileSync(resolve(here, '../services/diffstream/fixtures', fixture), 'utf8'));
  assert.deepEqual(parseDiffPayload(value), value);
}
assert.throws(
  () => parseDiffPayload({ contentType: 'application/json' }),
  /contentType/,
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
const nextChangedWorkspaceEvent = streamIterator.next();
transport.push({
  messageId: transport.sent[1].messageId,
  kind: 'stream-event',
  method: 'workspace.status.subscribe',
  streamId: 's000001',
  payload: {
    streamId: 's000001',
    seq: 2,
    event: 'snapshot',
    payload: { repos: [{ path: '', name: 'repo', dirty: true }] },
  },
});
const changedWorkspaceStreamEvent = await nextChangedWorkspaceEvent;
assert.equal(changedWorkspaceStreamEvent.value.seq, 2);
assert.deepEqual(changedWorkspaceStreamEvent.value.payload, { repos: [{ path: '', name: 'repo', dirty: true }] });

const treeIterator = client.subscribe('tree.subscribe')[Symbol.asyncIterator]();
const nextTreeEvent = treeIterator.next();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(transport.sent.length, 3);
assert.equal(transport.sent[2].method, 'tree.subscribe');
assert.equal(transport.sent[2].streamId, 's000002');
transport.push({
  messageId: transport.sent[2].messageId,
  kind: 'stream-event',
  method: 'tree.subscribe',
  streamId: 's000002',
  payload: {
    streamId: 's000002',
    seq: 1,
    event: 'snapshot',
    payload: { version: 'v1', entries: [{ repoPath: '', path: 'README.md', kind: 'file' }] },
  },
});
const treeStreamEvent = await nextTreeEvent;
assert.equal(treeStreamEvent.value.event, 'snapshot');
assert.deepEqual(treeStreamEvent.value.payload, {
  version: 'v1',
  entries: [{ repoPath: '', path: 'README.md', kind: 'file' }],
});

const presenceIterator = client.subscribe('peer.presence.subscribe')[Symbol.asyncIterator]();
const nextPresenceEvent = presenceIterator.next();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(transport.sent.length, 4);
assert.equal(transport.sent[3].method, 'peer.presence.subscribe');
assert.equal(transport.sent[3].streamId, 's000003');
transport.push({
  messageId: transport.sent[3].messageId,
  kind: 'stream-event',
  method: 'peer.presence.subscribe',
  streamId: 's000003',
  payload: {
    streamId: 's000003',
    seq: 1,
    event: 'snapshot',
    payload: { peers: [{ id: 'alice', name: 'Alice', online: true }] },
  },
});
const presenceStreamEvent = await nextPresenceEvent;
assert.deepEqual(presenceStreamEvent.value.payload, {
  peers: [{ id: 'alice', name: 'Alice', online: true }],
});
assert.deepEqual(parsePeerPresencePayload(presenceStreamEvent.value.payload), {
  peers: [{
    id: 'alice',
    name: 'Alice',
    sshAddress: '',
    location: '',
    os: null,
    shells: [],
    online: true,
    isSelf: false,
    status: 'online',
    summary: '',
    lastSeenAt: null,
  }],
});
assert.throws(
  () => parsePeerPresencePayload({ peers: [{ id: 'bad', status: 'maybe' }] }),
  /presence status/,
);
assert.deepEqual(parsePeerHealth({
  peerId: 'alice',
  status: 'configured',
  summary: 'Configured; not connected',
  checks: [{ id: 'bootstrap', status: 'pending', summary: 'Bootstrap has not run yet' }],
  updatedAt: 1,
}), {
  peerId: 'alice',
  status: 'configured',
  summary: 'Configured; not connected',
  checks: [{ id: 'bootstrap', status: 'pending', summary: 'Bootstrap has not run yet' }],
  updatedAt: 1,
});

const chatIterator = client.subscribe('chat.subscribe')[Symbol.asyncIterator]();
const nextChatEvent = chatIterator.next();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(transport.sent.length, 5);
assert.equal(transport.sent[4].method, 'chat.subscribe');
assert.equal(transport.sent[4].streamId, 's000004');
transport.push({
  messageId: transport.sent[4].messageId,
  kind: 'stream-event',
  method: 'chat.subscribe',
  streamId: 's000004',
  payload: {
    streamId: 's000004',
    seq: 1,
    event: 'snapshot',
    payload: { messages: [{ id: '1-me-000001', senderId: 'me', ts: 1, text: 'hi', links: [] }] },
  },
});
const chatStreamEvent = await nextChatEvent;
assert.deepEqual(chatStreamEvent.value.payload, {
  messages: [{ id: '1-me-000001', senderId: 'me', ts: 1, text: 'hi', links: [] }],
});

const routedRequestPromise = client.routeRequest('alice', 'deps.get', { workspace: 'main' });
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(transport.sent.length, 6);
assert.equal(transport.sent[5].method, 'hub.route.request');
assert.deepEqual(transport.sent[5].payload, {
  targetPeerId: 'alice',
  method: 'deps.get',
  payload: { workspace: 'main' },
});
transport.push({
  messageId: transport.sent[5].messageId,
  kind: 'response',
  method: 'hub.route.request',
  payload: { repos: ['remote'], edges: [] },
});
assert.deepEqual((await routedRequestPromise).payload, { repos: ['remote'], edges: [] });

const routedIterator = client.routeSubscribe('alice', 'workspace.status.subscribe')[Symbol.asyncIterator]();
const nextRoutedEvent = routedIterator.next();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(transport.sent.length, 7);
assert.equal(transport.sent[6].method, 'hub.route.subscribe');
assert.equal(transport.sent[6].streamId, 's000005');
assert.deepEqual(transport.sent[6].payload, {
  targetPeerId: 'alice',
  method: 'workspace.status.subscribe',
  payload: {},
});
transport.push({
  messageId: transport.sent[6].messageId,
  kind: 'stream-event',
  method: 'hub.route.subscribe',
  streamId: 's000005',
  payload: {
    streamId: 's000005',
    seq: 1,
    event: 'snapshot',
    payload: { repos: [{ path: '', name: 'remote' }] },
  },
});
const routedEvent = await nextRoutedEvent;
assert.deepEqual(routedEvent.value.payload, { repos: [{ path: '', name: 'remote' }] });

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

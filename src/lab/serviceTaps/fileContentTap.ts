import { createAsyncStreamMultiTap, type DestinationParams, type Tap } from '@owebeeone/grip-react';
import {
  ACTIVE_FILE,
  FILE_CONTENT,
  FILE_GIT_STATUS,
  FILE_LINE_INDEX,
  FILE_REF,
  FILE_STREAM_STATUS,
  FILE_WINDOW,
  SELECTED_PEER_ID,
} from '../grips';
import { LAB_HUB_ROUTE } from '../dataMode';
import { TextWindowReassembler, parseTextWindowDelta, parseTextWindowSnapshot } from '../serviceClient/filedelta/index.ts';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { ServiceStreamEvent } from '../serviceClient/protocol.ts';
import type { FileRef, FileStreamStatus, LineWindow } from '../types';
import type { ResetEvent } from '../serviceClient/filedelta/index.ts';
import { SERVICE_STREAM_RETRY } from './retry';

type FileOuts = {
  content: typeof FILE_CONTENT;
  gitStatus: typeof FILE_GIT_STATUS;
  status: typeof FILE_STREAM_STATUS;
  lineIndex: typeof FILE_LINE_INDEX;
};

interface FileKey {
  repoPath: string;
  path: string;
}

const reassemblers = new Map<string, TextWindowReassembler>();

export function createServiceFileContentTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<FileOuts, ServiceStreamEvent>({
    provides: [FILE_CONTENT, FILE_GIT_STATUS, FILE_STREAM_STATUS, FILE_LINE_INDEX],
    destinationParamGrips: [ACTIVE_FILE, FILE_REF, FILE_WINDOW],
    homeParamGrips: [SELECTED_PEER_ID],
    requestKeyOf: (params) => {
      const activeFile = params.getDestParam(ACTIVE_FILE) ?? '';
      if (!activeFile) return undefined;
      const ref = params.getDestParam(FILE_REF) ?? 'working';
      const window = params.getDestParam(FILE_WINDOW) ?? { lineStart: 0, lineEnd: 400 };
      const peerId = params.getHomeParam(SELECTED_PEER_ID) ?? 'me';
      return fileRequestKey(params.destContext.id, peerId, activeFile, ref, window);
    },
    subscribe: (params, signal) => {
      const activeFile = params.getDestParam(ACTIVE_FILE) ?? '';
      const ref = params.getDestParam(FILE_REF) ?? 'working';
      const window = params.getDestParam(FILE_WINDOW) ?? { lineStart: 0, lineEnd: 400 };
      const peerId = params.getHomeParam(SELECTED_PEER_ID) ?? 'me';
      const file = splitFileKey(activeFile);
      const payload = {
        repoPath: file.repoPath,
        path: file.path,
        ref,
        window,
      };
      if (LAB_HUB_ROUTE) return client.routeSubscribe(peerId, 'file.subscribe', payload, signal);
      return client.subscribe('file.subscribe', payload, signal);
    },
    mapEvent: (params, event) => mapFileEvent(params, event),
    getResetUpdates: () => statusUpdates('', { status: 'idle', error: null }, []),
    initialState: [
      [FILE_CONTENT, ''],
      [FILE_GIT_STATUS, 'clean'],
      [FILE_STREAM_STATUS, { status: 'idle', error: null }],
      [FILE_LINE_INDEX, []],
    ],
    onError: (_error, requestKey) => {
      reassemblers.delete(requestKey);
    },
    retry: SERVICE_STREAM_RETRY,
  }) as unknown as Tap;
}

function mapFileEvent(params: DestinationParams, event: ServiceStreamEvent) {
  const activeFile = params.getDestParam(ACTIVE_FILE) ?? '';
  const ref = params.getDestParam(FILE_REF) ?? 'working';
  const window = params.getDestParam(FILE_WINDOW) ?? { lineStart: 0, lineEnd: 400 };
  const peerId = params.getHomeParam(SELECTED_PEER_ID) ?? 'me';
  const requestKey = fileRequestKey(params.destContext.id, peerId, activeFile, ref, window);
  const reassembler = getReassembler(requestKey);

  if (event.event === 'error') {
    const message = typeof event.payload.message === 'string' ? event.payload.message : 'file stream error';
    return statusUpdates('', { status: 'error', error: message }, []);
  }
  if (event.event === 'closed') {
    return statusUpdates(reassembler.snapshot?.data ? reassembler.text : '', { status: 'idle', error: null }, reassembler.snapshot?.lineIndex ?? []);
  }
  if (event.event === 'snapshot') {
    const snapshot = parseTextWindowSnapshot(event.payload);
    reassembler.applySnapshot(snapshot);
    return statusUpdates(reassembler.text, { status: 'ready', error: null }, snapshot.lineIndex);
  }
  if (event.event === 'delta') {
    const snapshot = reassembler.applyDelta(parseTextWindowDelta(event.payload));
    return statusUpdates(reassembler.text, { status: 'ready', error: null }, snapshot.lineIndex);
  }
  if (event.event === 'reset') {
    const reset = parseResetEvent(event.payload);
    const snapshot = reassembler.applyReset(reset);
    return statusUpdates(reassembler.text, { status: 'ready', error: null }, snapshot.lineIndex);
  }
  return statusUpdates(reassembler.snapshot?.data ? reassembler.text : '', { status: 'loading', error: null }, reassembler.snapshot?.lineIndex ?? []);
}

function statusUpdates(content: string, status: FileStreamStatus, lineIndex: number[]) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const values = new Map<any, any>();
  values.set(FILE_CONTENT, content);
  values.set(FILE_GIT_STATUS, 'clean');
  values.set(FILE_STREAM_STATUS, status);
  values.set(FILE_LINE_INDEX, lineIndex);
  return values;
}

function getReassembler(requestKey: string): TextWindowReassembler {
  let reassembler = reassemblers.get(requestKey);
  if (!reassembler) {
    reassembler = new TextWindowReassembler();
    reassemblers.set(requestKey, reassembler);
  }
  return reassembler;
}

function fileRequestKey(contextId: string, peerId: string, activeFile: string, ref: FileRef, window: LineWindow): string {
  return `${contextId}|${peerId}|${activeFile}|${ref}|${window.lineStart}:${window.lineEnd}`;
}

function splitFileKey(key: string): FileKey {
  const i = key.indexOf('::');
  if (i < 0) return { repoPath: '', path: key };
  return { repoPath: key.slice(0, i), path: key.slice(i + 2) };
}

function parseResetEvent(value: Record<string, unknown>): ResetEvent {
  if (value.type !== 'reset') throw new Error('reset type expected');
  if (typeof value.reason !== 'string') throw new Error('reset reason expected');
  if (typeof value.seq !== 'number') throw new Error('reset seq expected');
  return {
    type: 'reset',
    reason: value.reason,
    seq: value.seq,
    snapshot: parseTextWindowSnapshot(value.snapshot),
  };
}

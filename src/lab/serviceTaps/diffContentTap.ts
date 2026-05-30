import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import {
  ACTIVE_FILE,
  DIFF_LEFT,
  DIFF_RIGHT,
  DIFF_WINDOW,
} from '../grips';
import {
  DIFF_DIAGNOSTICS,
  DIFF_HUNKS,
  DIFF_STREAM_STATUS,
  DIFF_VERSION,
} from '../grips.service';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import { parseDiffPayload, type DiffEndpoint as ServiceDiffEndpoint } from '../serviceClient/diff/index.ts';
import type { ServiceStreamEvent } from '../serviceClient/protocol.ts';
import type { DiffEndpoint, DiffStreamStatus, LineWindow } from '../types';
import { SERVICE_STREAM_RETRY } from './retry';

type DiffOuts = {
  hunks: typeof DIFF_HUNKS;
  diagnostics: typeof DIFF_DIAGNOSTICS;
  status: typeof DIFF_STREAM_STATUS;
  version: typeof DIFF_VERSION;
};

interface FileKey {
  repoPath: string;
  path: string;
}

export function createServiceDiffContentTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<DiffOuts, ServiceStreamEvent>({
    provides: [DIFF_HUNKS, DIFF_DIAGNOSTICS, DIFF_STREAM_STATUS, DIFF_VERSION],
    destinationParamGrips: [ACTIVE_FILE, DIFF_LEFT, DIFF_RIGHT, DIFF_WINDOW],
    requestKeyOf: (params) => {
      const activeFile = params.getDestParam(ACTIVE_FILE) ?? '';
      if (!activeFile) return undefined;
      const left = params.getDestParam(DIFF_LEFT) ?? DIFF_LEFT.defaultValue!;
      const right = params.getDestParam(DIFF_RIGHT) ?? DIFF_RIGHT.defaultValue!;
      const window = params.getDestParam(DIFF_WINDOW) ?? { lineStart: 0, lineEnd: 400 };
      return diffRequestKey(params.destContext.id, activeFile, left, right, window);
    },
    subscribe: (params, signal) => {
      const activeFile = params.getDestParam(ACTIVE_FILE) ?? '';
      const left = params.getDestParam(DIFF_LEFT) ?? DIFF_LEFT.defaultValue!;
      const right = params.getDestParam(DIFF_RIGHT) ?? DIFF_RIGHT.defaultValue!;
      const window = params.getDestParam(DIFF_WINDOW) ?? { lineStart: 0, lineEnd: 400 };
      const file = splitFileKey(activeFile);
      return client.subscribe('diff.subscribe', {
        left: endpointPayload(left, file),
        right: endpointPayload(right, file),
        window,
        contextLines: 3,
      }, signal);
    },
    mapEvent: (_params, event) => mapDiffEventToUpdates(event),
    getResetUpdates: () => diffUpdates([], [], { status: 'idle', error: null }, ''),
    initialState: [
      [DIFF_HUNKS, []],
      [DIFF_DIAGNOSTICS, []],
      [DIFF_STREAM_STATUS, { status: 'idle', error: null }],
      [DIFF_VERSION, ''],
    ],
    retry: SERVICE_STREAM_RETRY,
  }) as unknown as Tap;
}

export function mapDiffEventToUpdates(event: ServiceStreamEvent) {
  if (event.event === 'error') {
    const message = typeof event.payload.message === 'string' ? event.payload.message : 'diff stream error';
    return diffUpdates([], [], { status: 'error', error: message }, '');
  }
  if (event.event !== 'snapshot' && event.event !== 'reset') {
    return diffUpdates([], [], { status: 'loading', error: null }, '');
  }
  const payload = parseDiffPayload(event.payload);
  const status: DiffStreamStatus = payload.diagnostics.length > 0
    ? { status: 'error', error: payload.diagnostics[0]?.message ?? 'diff diagnostic' }
    : { status: 'ready', error: null };
  return diffUpdates(payload.hunks, payload.diagnostics, status, payload.version);
}

function diffUpdates(
  hunks: unknown[],
  diagnostics: unknown[],
  status: DiffStreamStatus,
  version: string,
) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const values = new Map<any, any>();
  values.set(DIFF_HUNKS, hunks);
  values.set(DIFF_DIAGNOSTICS, diagnostics);
  values.set(DIFF_STREAM_STATUS, status);
  values.set(DIFF_VERSION, version);
  return values;
}

function endpointPayload(endpoint: DiffEndpoint, file: FileKey): ServiceDiffEndpoint {
  return {
    peerId: endpoint.peerId,
    repoPath: file.repoPath,
    path: file.path,
    ref: { kind: endpoint.ref },
  };
}

function diffRequestKey(
  contextId: string,
  activeFile: string,
  left: DiffEndpoint,
  right: DiffEndpoint,
  window: LineWindow,
): string {
  return [
    contextId,
    activeFile,
    `${left.peerId}:${left.ref}`,
    `${right.peerId}:${right.ref}`,
    `${window.lineStart}:${window.lineEnd}`,
  ].join('|');
}

function splitFileKey(key: string): FileKey {
  const i = key.indexOf('::');
  if (i < 0) return { repoPath: '', path: key };
  return { repoPath: key.slice(0, i), path: key.slice(i + 2) };
}

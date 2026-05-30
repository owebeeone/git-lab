import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import {
  SELECTED_SESSION,
  SELECTED_TARGET,
  SESSIONS,
  SESSION_DIAGNOSTICS,
  SESSION_OUTPUT,
  SESSION_OUTPUT_SOURCE,
} from '../grips';
import { LAB_HUB_ROUTE } from '../dataMode';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { ServiceStreamEvent } from '../serviceClient/protocol.ts';
import { parseDiagnostics } from '../sessionOutputTap';
import { SERVICE_STREAM_RETRY } from './retry';
import type { CommandSession } from '../types';

interface SessionOutputPayload {
  output: string;
  exitCode: number | null;
  durationMs?: number | null;
  userMs?: number | null;
  systemMs?: number | null;
}

type SessionOutputOuts = {
  output: typeof SESSION_OUTPUT;
  source: typeof SESSION_OUTPUT_SOURCE;
  diagnostics: typeof SESSION_DIAGNOSTICS;
};

export function createServiceSessionOutputTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<SessionOutputOuts, ServiceStreamEvent>({
    provides: [SESSION_OUTPUT, SESSION_OUTPUT_SOURCE, SESSION_DIAGNOSTICS],
    homeParamGrips: [SESSIONS, SELECTED_SESSION, SELECTED_TARGET],
    requestKeyOf: (params) => {
      const sessionId = params.getHomeParam(SELECTED_SESSION);
      if (!sessionId) return undefined;
      const repoPath = params.getHomeParam(SELECTED_TARGET) ?? '';
      const peerId = routePeer(params, sessionId);
      return `session.output|${peerId}|${sessionId}|${repoPath}`;
    },
    subscribe: (params, signal) => {
      const sessionId = params.getHomeParam(SELECTED_SESSION) ?? '';
      const peerId = routePeer(params, sessionId);
      const repoPath = params.getHomeParam(SELECTED_TARGET) ?? '';
      if (LAB_HUB_ROUTE) return client.routeSubscribe(peerId, 'session.output.subscribe', { sessionId, repoPath }, signal);
      return client.subscribe('session.output.subscribe', { sessionId, repoPath }, signal);
    },
    mapEvent: (params, event) => {
      const payload = event.payload as unknown as SessionOutputPayload;
      const sessionId = params.getHomeParam(SELECTED_SESSION) ?? '';
      const peerId = routePeer(params, sessionId);
      const repoPath = params.getHomeParam(SELECTED_TARGET) ?? '';
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const values = new Map<any, any>();
      values.set(SESSION_OUTPUT, payload.output ?? '');
      values.set(SESSION_OUTPUT_SOURCE, { peerId, sessionId, repoPath });
      values.set(SESSION_DIAGNOSTICS, parseDiagnostics(payload.output ?? '', payload.exitCode ?? null));
      return values;
    },
    initialState: [
      [SESSION_OUTPUT, ''],
      [SESSION_OUTPUT_SOURCE, null],
      [SESSION_DIAGNOSTICS, { kind: 'none', failed: 0, passed: 0, failures: [] }],
    ],
    retry: SERVICE_STREAM_RETRY,
  }) as unknown as Tap;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function routePeer(params: { getHomeParam: (grip: any) => unknown }, sessionId: string): string {
  const sessions = params.getHomeParam(SESSIONS) as CommandSession[] | undefined;
  return sessions?.find((session) => session.id === sessionId)?.peerId ?? 'me';
}

import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import {
  SELECTED_SESSION,
  SELECTED_PEER_ID,
  SELECTED_TARGET,
  SESSION_DIAGNOSTICS,
  SESSION_OUTPUT,
} from '../grips';
import { LAB_HUB_ROUTE } from '../dataMode';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { ServiceStreamEvent } from '../serviceClient/protocol.ts';
import { parseDiagnostics } from '../sessionOutputTap';

interface SessionOutputPayload {
  output: string;
  exitCode: number | null;
}

type SessionOutputOuts = {
  output: typeof SESSION_OUTPUT;
  diagnostics: typeof SESSION_DIAGNOSTICS;
};

export function createServiceSessionOutputTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<SessionOutputOuts, ServiceStreamEvent>({
    provides: [SESSION_OUTPUT, SESSION_DIAGNOSTICS],
    homeParamGrips: [SELECTED_PEER_ID, SELECTED_SESSION, SELECTED_TARGET],
    requestKeyOf: (params) => {
      const sessionId = params.getHomeParam(SELECTED_SESSION);
      if (!sessionId) return undefined;
      const repoPath = params.getHomeParam(SELECTED_TARGET) ?? '';
      const peerId = params.getHomeParam(SELECTED_PEER_ID) ?? 'me';
      return `session.output|${peerId}|${sessionId}|${repoPath}`;
    },
    subscribe: (params, signal) => {
      const peerId = params.getHomeParam(SELECTED_PEER_ID) ?? 'me';
      const sessionId = params.getHomeParam(SELECTED_SESSION) ?? '';
      const repoPath = params.getHomeParam(SELECTED_TARGET) ?? '';
      if (LAB_HUB_ROUTE) return client.routeSubscribe(peerId, 'session.output.subscribe', { sessionId, repoPath }, signal);
      return client.subscribe('session.output.subscribe', { sessionId, repoPath }, signal);
    },
    mapEvent: (_params, event) => {
      const payload = event.payload as unknown as SessionOutputPayload;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const values = new Map<any, any>();
      values.set(SESSION_OUTPUT, payload.output ?? '');
      values.set(SESSION_DIAGNOSTICS, parseDiagnostics(payload.output ?? '', payload.exitCode ?? null));
      return values;
    },
    initialState: [
      [SESSION_OUTPUT, ''],
      [SESSION_DIAGNOSTICS, { kind: 'none', failed: 0, passed: 0, failures: [] }],
    ],
  }) as unknown as Tap;
}

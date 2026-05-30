import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { SELECTED_PEER_ID, SESSIONS } from '../grips';
import { LAB_HUB_ROUTE } from '../dataMode';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { ServiceStreamEvent } from '../serviceClient/protocol.ts';
import type { CommandSession } from '../types';
import { SERVICE_STREAM_RETRY } from './retry';

interface SessionsPayload {
  sessions: CommandSession[];
}

type SessionsOuts = {
  sessions: typeof SESSIONS;
};

export function createServiceSessionsTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<SessionsOuts, ServiceStreamEvent>({
    provides: [SESSIONS],
    homeParamGrips: [SELECTED_PEER_ID],
    requestKeyOf: (params) => `sessions:${routePeer(params)}`,
    subscribe: (params, signal) => {
      const peerId = routePeer(params);
      if (LAB_HUB_ROUTE) return client.routeSubscribe(peerId, 'sessions.subscribe', {}, signal);
      return client.subscribe('sessions.subscribe', {}, signal);
    },
    mapEvent: (_params, event) => {
      const payload = event.payload as unknown as SessionsPayload;
      return new Map([[SESSIONS, payload.sessions ?? []]]);
    },
    initialState: [[SESSIONS, []]],
    retry: SERVICE_STREAM_RETRY,
  }) as unknown as Tap;
}

function routePeer(params: { getHomeParam: (grip: typeof SELECTED_PEER_ID) => string | undefined }): string {
  return params.getHomeParam(SELECTED_PEER_ID) ?? 'me';
}

import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { SESSIONS } from '../grips';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { ServiceStreamEvent } from '../serviceClient/protocol.ts';
import type { CommandSession } from '../types';

interface SessionsPayload {
  sessions: CommandSession[];
}

type SessionsOuts = {
  sessions: typeof SESSIONS;
};

export function createServiceSessionsTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<SessionsOuts, ServiceStreamEvent>({
    provides: [SESSIONS],
    requestKeyOf: () => 'sessions',
    subscribe: (_params, signal) => client.subscribe('sessions.subscribe', {}, signal),
    mapEvent: (_params, event) => {
      const payload = event.payload as unknown as SessionsPayload;
      return new Map([[SESSIONS, payload.sessions ?? []]]);
    },
    initialState: [[SESSIONS, []]],
  }) as unknown as Tap;
}

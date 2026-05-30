import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { PEERS } from '../grips';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import { parsePeerPresencePayload, type ServiceStreamEvent } from '../serviceClient/protocol.ts';
import type { Peer } from '../types';

type PeersOuts = {
  peers: typeof PEERS;
};

export function createServicePeersTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<PeersOuts, ServiceStreamEvent>({
    provides: [PEERS],
    requestKeyOf: () => 'peer.presence',
    subscribe: (_params, signal) => client.subscribe('peer.presence.subscribe', {}, signal),
    mapEvent: (_params, event) => {
      const payload = parsePeerPresencePayload(event.payload);
      return new Map([[PEERS, payload.peers as Peer[]]]);
    },
    getResetUpdates: () => new Map(),
    retry: {
      initialDelayMs: 500,
      maxDelayMs: 5000,
      backoffMultiplier: 2,
      jitterRatio: 0.4,
    },
  }) as unknown as Tap;
}

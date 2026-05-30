import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { SELECTED_PEER_ID, WORKSPACE_DEP_EDGES } from '../grips';
import { LAB_HUB_ROUTE } from '../dataMode';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { DependencyEdge } from '../types';

interface DepsGraphPayload {
  repos: string[];
  edges: DependencyEdge[];
  errors: Record<string, string>;
}

type DepsGraphOuts = {
  edges: typeof WORKSPACE_DEP_EDGES;
};

export function createServiceDepsGraphTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<DepsGraphOuts, DepsGraphPayload>({
    provides: [WORKSPACE_DEP_EDGES],
    homeParamGrips: [SELECTED_PEER_ID],
    requestKeyOf: (params) => `deps.get:${routePeer(params)}`,
    subscribe: async function* (params, signal) {
      const peerId = routePeer(params);
      const response = LAB_HUB_ROUTE
        ? await client.routeRequest(peerId, 'deps.get', {}, signal)
        : await client.request('deps.get', {}, signal);
      yield response.payload as unknown as DepsGraphPayload;
    },
    mapEvent: (_params, event) => new Map([[WORKSPACE_DEP_EDGES, event.edges]]),
    initialState: [[WORKSPACE_DEP_EDGES, []]],
  }) as unknown as Tap;
}

function routePeer(params: { getHomeParam: (grip: typeof SELECTED_PEER_ID) => string | undefined }): string {
  return params.getHomeParam(SELECTED_PEER_ID) ?? 'me';
}

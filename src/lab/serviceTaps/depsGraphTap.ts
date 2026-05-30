import { createAsyncMultiTap, type Tap } from '@owebeeone/grip-react';
import { SELECTED_PEER_ID, WORKSPACE_DEP_EDGES } from '../grips';
import { LAB_HUB_ROUTE } from '../dataMode';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { DependencyEdge } from '../types';
import { SERVICE_STREAM_RETRY } from './retry';

interface DepsGraphPayload {
  repos: string[];
  edges: DependencyEdge[];
  errors: Record<string, string>;
}

type DepsGraphOuts = {
  edges: typeof WORKSPACE_DEP_EDGES;
};

export function createServiceDepsGraphTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncMultiTap<DepsGraphOuts, DepsGraphPayload>({
    provides: [WORKSPACE_DEP_EDGES],
    homeParamGrips: [SELECTED_PEER_ID],
    requestKeyOf: (params) => `deps.get:${routePeer(params)}`,
    fetcher: async (params, signal) => {
      const peerId = routePeer(params);
      const response = LAB_HUB_ROUTE
        ? await client.routeRequest(peerId, 'deps.get', {}, signal)
        : await client.request('deps.get', {}, signal);
      return response.payload as unknown as DepsGraphPayload;
    },
    mapResult: (_params, result) => new Map([[WORKSPACE_DEP_EDGES, result.edges]]),
    initialState: [[WORKSPACE_DEP_EDGES, []]],
    cacheTtlMs: 30_000,
    retry: SERVICE_STREAM_RETRY,
  }) as unknown as Tap;
}

function routePeer(params: { getHomeParam: (grip: typeof SELECTED_PEER_ID) => string | undefined }): string {
  return params.getHomeParam(SELECTED_PEER_ID) ?? 'me';
}

import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { WORKSPACE_DEP_EDGES } from '../grips';
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
    requestKeyOf: () => 'deps.get',
    subscribe: async function* (_params, signal) {
      const response = await client.request('deps.get', {}, signal);
      yield response.payload as unknown as DepsGraphPayload;
    },
    mapEvent: (_params, event) => new Map([[WORKSPACE_DEP_EDGES, event.edges]]),
    initialState: [[WORKSPACE_DEP_EDGES, []]],
  }) as unknown as Tap;
}

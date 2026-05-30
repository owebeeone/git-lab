import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { SELECTED_PEER_ID, WORKSPACE_TREE, WORKSPACE_TREE_VERSION } from '../grips';
import { LAB_HUB_ROUTE } from '../dataMode';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { ServiceStreamEvent } from '../serviceClient/protocol.ts';
import type { WorkspaceTreeEntry } from '../types';
import { SERVICE_STREAM_RETRY } from './retry';

interface TreePayload {
  version: string;
  entries: WorkspaceTreeEntry[];
}

type TreeOuts = {
  tree: typeof WORKSPACE_TREE;
  version: typeof WORKSPACE_TREE_VERSION;
};

export function createServiceTreeTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<TreeOuts, ServiceStreamEvent>({
    provides: [WORKSPACE_TREE, WORKSPACE_TREE_VERSION],
    homeParamGrips: [SELECTED_PEER_ID],
    requestKeyOf: (params) => `tree:${routePeer(params)}`,
    subscribe: (params, signal) => {
      const peerId = routePeer(params);
      if (LAB_HUB_ROUTE) return client.routeSubscribe(peerId, 'tree.subscribe', {}, signal);
      return client.subscribe('tree.subscribe', {}, signal);
    },
    mapEvent: (_params, event) => {
      const payload = event.payload as unknown as TreePayload;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const values = new Map<any, any>();
      values.set(WORKSPACE_TREE, payload.entries ?? []);
      values.set(WORKSPACE_TREE_VERSION, payload.version ?? '');
      return values;
    },
    initialState: [
      [WORKSPACE_TREE, []],
      [WORKSPACE_TREE_VERSION, ''],
    ],
    retry: SERVICE_STREAM_RETRY,
  }) as unknown as Tap;
}

function routePeer(params: { getHomeParam: (grip: typeof SELECTED_PEER_ID) => string | undefined }): string {
  return params.getHomeParam(SELECTED_PEER_ID) ?? 'me';
}

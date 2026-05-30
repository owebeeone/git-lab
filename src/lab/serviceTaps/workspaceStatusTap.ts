import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { SELECTED_PEER_ID, WORKSPACE_REPOS } from '../grips';
import { LAB_HUB_ROUTE } from '../dataMode';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { RepoStatus } from '../types';
import type { ServiceStreamEvent } from '../serviceClient/protocol.ts';

interface WorkspaceStatusPayload {
  repos: RepoStatus[];
}

type WorkspaceStatusOuts = {
  repos: typeof WORKSPACE_REPOS;
};

export function createServiceWorkspaceStatusTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<WorkspaceStatusOuts, ServiceStreamEvent>({
    provides: [WORKSPACE_REPOS],
    homeParamGrips: [SELECTED_PEER_ID],
    requestKeyOf: (params) => `workspace.status:${routePeer(params)}`,
    subscribe: (params, signal) => {
      const peerId = routePeer(params);
      if (LAB_HUB_ROUTE) return client.routeSubscribe(peerId, 'workspace.status.subscribe', {}, signal);
      return client.subscribe('workspace.status.subscribe', {}, signal);
    },
    mapEvent: (_params, event) => {
      const payload = event.payload as unknown as WorkspaceStatusPayload;
      return new Map([[WORKSPACE_REPOS, payload.repos]]);
    },
    initialState: [[WORKSPACE_REPOS, []]],
  }) as unknown as Tap;
}

function routePeer(params: { getHomeParam: (grip: typeof SELECTED_PEER_ID) => string | undefined }): string {
  return params.getHomeParam(SELECTED_PEER_ID) ?? 'me';
}

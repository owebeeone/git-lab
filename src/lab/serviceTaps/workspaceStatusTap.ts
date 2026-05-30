import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { WORKSPACE_REPOS } from '../grips';
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
    requestKeyOf: () => 'workspace.status',
    subscribe: (_params, signal) => client.subscribe('workspace.status.subscribe', {}, signal),
    mapEvent: (_params, event) => {
      const payload = event.payload as unknown as WorkspaceStatusPayload;
      return new Map([[WORKSPACE_REPOS, payload.repos]]);
    },
    initialState: [[WORKSPACE_REPOS, []]],
  }) as unknown as Tap;
}

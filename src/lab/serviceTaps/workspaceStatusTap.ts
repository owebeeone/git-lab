import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { WORKSPACE_REPOS } from '../grips';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { RepoStatus } from '../types';

interface WorkspaceStatusPayload {
  repos: RepoStatus[];
}

type WorkspaceStatusOuts = {
  repos: typeof WORKSPACE_REPOS;
};

export function createServiceWorkspaceStatusTap(client: ServiceClient = defaultServiceClient): Tap {
  return createAsyncStreamMultiTap<WorkspaceStatusOuts, WorkspaceStatusPayload>({
    provides: [WORKSPACE_REPOS],
    requestKeyOf: () => 'workspace.status',
    subscribe: async function* (_params, signal) {
      yield await client.getJson<WorkspaceStatusPayload>('/workspace/status', signal);
    },
    mapEvent: (_params, event) => new Map([[WORKSPACE_REPOS, event.repos]]),
    initialState: [[WORKSPACE_REPOS, []]],
  }) as unknown as Tap;
}

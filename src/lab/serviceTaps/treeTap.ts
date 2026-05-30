import { createAsyncStreamMultiTap, type Tap } from '@owebeeone/grip-react';
import { WORKSPACE_TREE, WORKSPACE_TREE_VERSION } from '../grips';
import { defaultServiceClient, type ServiceClient } from '../serviceClient/client.ts';
import type { ServiceStreamEvent } from '../serviceClient/protocol.ts';
import type { WorkspaceTreeEntry } from '../types';

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
    requestKeyOf: () => 'tree',
    subscribe: (_params, signal) => client.subscribe('tree.subscribe', {}, signal),
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
  }) as unknown as Tap;
}

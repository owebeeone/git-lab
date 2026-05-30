import { createFunctionTap, type Tap } from '@owebeeone/grip-react';
import { WORKSPACE_REPOS } from '../grips';

export function createServiceWorkspaceStatusTap(): Tap {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return createFunctionTap<any, any, any, any>({
    provides: [WORKSPACE_REPOS],
    compute: () => new Map([[WORKSPACE_REPOS, []]]),
  }) as unknown as Tap;
}

import { createFunctionTap, type Tap } from '@owebeeone/grip-react';
import { WORKSPACE_DEP_EDGES } from '../grips';

export function createServiceDepsGraphTap(): Tap {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return createFunctionTap<any, any, any, any>({
    provides: [WORKSPACE_DEP_EDGES],
    compute: () => new Map([[WORKSPACE_DEP_EDGES, []]]),
  }) as unknown as Tap;
}

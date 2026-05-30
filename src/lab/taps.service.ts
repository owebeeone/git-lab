import { createFunctionTap, type Tap } from '@owebeeone/grip-react';
import { grok } from '../runtime';
import {
  FILE_CONTENT,
  FILE_GIT_STATUS,
  GRAPH_NODES,
  SESSION_DIAGNOSTICS,
  SESSION_OUTPUT,
} from './grips';
import { createServiceDepsGraphTap } from './serviceTaps/depsGraphTap';
import { createServiceTreeTap } from './serviceTaps/treeTap';
import { createServiceWorkspaceStatusTap } from './serviceTaps/workspaceStatusTap';
import { createServiceStateTap } from './serviceStateTap';
import { registerLabUiTaps } from './taps';

function registerServicePlaceholderTaps() {
  grok.registerTap(createFunctionTap({
    provides: [GRAPH_NODES],
    compute: () => new Map([[GRAPH_NODES, []]]),
  }) as unknown as Tap);

  grok.registerTap(createFunctionTap({
    provides: [FILE_CONTENT, FILE_GIT_STATUS],
    compute: () => new Map([
      [FILE_CONTENT, ''],
      [FILE_GIT_STATUS, 'clean'],
    ]),
  }) as unknown as Tap);

  grok.registerTap(createFunctionTap({
    provides: [SESSION_OUTPUT, SESSION_DIAGNOSTICS],
    compute: () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const values = new Map<any, any>();
      values.set(SESSION_OUTPUT, '');
      values.set(SESSION_DIAGNOSTICS, { kind: 'none', failed: 0, passed: 0, failures: [] });
      return values;
    },
  }) as unknown as Tap);
}

export function registerLabServiceTaps() {
  registerLabUiTaps();
  grok.registerTap(createServiceStateTap());
  grok.registerTap(createServiceWorkspaceStatusTap());
  grok.registerTap(createServiceDepsGraphTap());
  grok.registerTap(createServiceTreeTap());
  registerServicePlaceholderTaps();
}

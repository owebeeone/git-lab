import { createFunctionTap, type Tap } from '@owebeeone/grip-react';
import { grok } from '../runtime';
import {
  GRAPH_NODES,
} from './grips';
import { createServiceDepsGraphTap } from './serviceTaps/depsGraphTap';
import { createServiceChatMessagesTap } from './serviceTaps/chatMessagesTap';
import { createServiceFileContentTap } from './serviceTaps/fileContentTap';
import { createServicePeersTap } from './serviceTaps/peersTap';
import { createServiceSessionOutputTap } from './serviceTaps/sessionOutputTap';
import { createServiceSessionsTap } from './serviceTaps/sessionsTap';
import { createServiceTreeTap } from './serviceTaps/treeTap';
import { createServiceWorkspaceStatusTap } from './serviceTaps/workspaceStatusTap';
import { createServiceStateTap } from './serviceStateTap';
import { LAB_HUB_PRESENCE, LAB_HUB_ROUTE } from './dataMode';
import { registerLabUiTaps } from './taps';

function registerServicePlaceholderTaps() {
  grok.registerTap(createFunctionTap({
    provides: [GRAPH_NODES],
    compute: () => new Map([[GRAPH_NODES, []]]),
  }) as unknown as Tap);
}

export function registerLabServiceTaps() {
  registerLabUiTaps();
  grok.registerTap(createServiceStateTap());
  grok.registerTap(createServiceWorkspaceStatusTap());
  grok.registerTap(createServiceDepsGraphTap());
  grok.registerTap(createServiceTreeTap());
  grok.registerTap(createServiceFileContentTap());
  grok.registerTap(createServiceSessionsTap());
  grok.registerTap(createServiceSessionOutputTap());
  grok.registerTap(createServiceChatMessagesTap());
  if (LAB_HUB_PRESENCE || LAB_HUB_ROUTE) grok.registerTap(createServicePeersTap());
  registerServicePlaceholderTaps();
}

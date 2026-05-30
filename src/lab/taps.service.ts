import { grok } from '../runtime';
import { registerGraphSimTap } from './graphEngine';
import { createServiceDepsGraphTap } from './serviceTaps/depsGraphTap';
import { createServiceChatMessagesTap } from './serviceTaps/chatMessagesTap';
import { createServiceDiffContentTap } from './serviceTaps/diffContentTap';
import { createServiceFileContentTap } from './serviceTaps/fileContentTap';
import { createServicePeersTap } from './serviceTaps/peersTap';
import { createServiceSessionOutputTap } from './serviceTaps/sessionOutputTap';
import { createServiceSessionsTap } from './serviceTaps/sessionsTap';
import { createServiceTreeTap } from './serviceTaps/treeTap';
import { createServiceWorkspaceStatusTap } from './serviceTaps/workspaceStatusTap';
import { createServiceStateTap } from './serviceStateTap';
import { registerLabUiTaps } from './taps';

function registerServicePlaceholderTaps() {
  registerGraphSimTap();
}

export function registerLabServiceTaps() {
  registerLabUiTaps({ registerPeersAtom: false });
  grok.registerTap(createServiceStateTap());
  grok.registerTap(createServiceWorkspaceStatusTap());
  grok.registerTap(createServiceDepsGraphTap());
  grok.registerTap(createServiceTreeTap());
  grok.registerTap(createServiceFileContentTap());
  grok.registerTap(createServiceDiffContentTap());
  grok.registerTap(createServiceSessionsTap());
  grok.registerTap(createServiceSessionOutputTap());
  grok.registerTap(createServiceChatMessagesTap());
  grok.registerTap(createServicePeersTap());
  registerServicePlaceholderTaps();
}

import { createFunctionTap, type Tap } from '@owebeeone/grip-react';
import { grok } from '../runtime';
import {
  ACTIVE_FILE, FILE_REF, FILE_CONTENT, FILE_GIT_STATUS,
  SELECTED_PEER_ID, PEERS,
} from './grips';
import { FILE_IMAGES } from './fakeData';
import { resolveContent } from './content';
import type { FileImage, FileRef, Peer } from './types';

function splitKey(key: string) {
  const i = key.indexOf('::');
  return { repoPath: key.slice(0, i), path: key.slice(i + 2) };
}

// Higher-level tap registered at the main context. Each editor column requests
// FILE_CONTENT from its own child context; this tap reads that context's
// destination params (ACTIVE_FILE, FILE_REF) plus the home param (selected
// peer) and computes the content for that specific destination. This is the
// seam where the real delta-protocol data source plugs in later.
export function registerFileContentTap() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tap = createFunctionTap<any, any, any, any>({
    provides: [FILE_CONTENT, FILE_GIT_STATUS],
    destinationParamGrips: [ACTIVE_FILE, FILE_REF],
    homeParamGrips: [SELECTED_PEER_ID, PEERS],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    compute: ({ getDestParam, getHomeParam }: any) => {
      const key: string = getDestParam(ACTIVE_FILE) ?? '';
      const ref: FileRef = getDestParam(FILE_REF) ?? 'working';
      const peerId: string = getHomeParam(SELECTED_PEER_ID) ?? '';
      const peers: Peer[] = getHomeParam(PEERS) ?? [];

      let content = '';
      let status = 'clean';
      if (key) {
        const img: FileImage | undefined = FILE_IMAGES.find((f) => `${f.repoPath}::${f.path}` === key);
        const { repoPath, path } = splitKey(key);
        content = img
          ? resolveContent(img, peerId, ref, peers)
          : `// ${repoPath}/${path}\n// (no preview available in the mock)\n`;
        status = img ? img.gitStatus : 'clean';
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return new Map<any, any>([[FILE_CONTENT, content], [FILE_GIT_STATUS, status]]);
    },
  });
  grok.registerTap(tap as unknown as Tap);
}

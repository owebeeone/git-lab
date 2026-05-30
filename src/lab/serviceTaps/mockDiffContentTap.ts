import { createFunctionTap, type Tap } from '@owebeeone/grip-react';
import { ACTIVE_FILE, DIFF_LEFT, DIFF_RIGHT, DIFF_WINDOW } from '../grips';
import {
  DIFF_DIAGNOSTICS,
  DIFF_HUNKS,
  DIFF_STREAM_STATUS,
  DIFF_VERSION,
} from '../grips.service';
import { resolveContent } from '../content';
import { lineDiff, rowsToDiffHunks } from '../diff';
import { FILE_IMAGES, INITIAL_PEERS } from '../fakeData';

export function createMockDiffContentTap(): Tap {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return createFunctionTap<any, any, any, any>({
    provides: [DIFF_HUNKS, DIFF_DIAGNOSTICS, DIFF_STREAM_STATUS, DIFF_VERSION],
    destinationParamGrips: [ACTIVE_FILE, DIFF_LEFT, DIFF_RIGHT, DIFF_WINDOW],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    compute: ({ getDestParam }: any) => {
      const activeFile = getDestParam(ACTIVE_FILE) ?? '';
      const left = getDestParam(DIFF_LEFT) ?? DIFF_LEFT.defaultValue!;
      const right = getDestParam(DIFF_RIGHT) ?? DIFF_RIGHT.defaultValue!;
      const file = FILE_IMAGES.find((item) => `${item.repoPath}::${item.path}` === activeFile) ?? FILE_IMAGES[0];
      const hunks = rowsToDiffHunks(lineDiff(
        resolveContent(file, left.peerId, left.ref, INITIAL_PEERS),
        resolveContent(file, right.peerId, right.ref, INITIAL_PEERS),
      ));
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const values = new Map<any, any>();
      values.set(DIFF_HUNKS, hunks);
      values.set(DIFF_DIAGNOSTICS, []);
      values.set(DIFF_STREAM_STATUS, { status: 'ready', error: null });
      values.set(DIFF_VERSION, 'mock');
      return values;
    },
  }) as unknown as Tap;
}

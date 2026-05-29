import type { ViewId, DiffEndpoint } from './types';

// A shareable slice of UI state. A link is just a URL that carries the grip
// name => value pairs needed to reproduce a view. Dropping/clicking the link
// applies those grips (see ChatView.openLink), restoring the exact state.
//
// URL shape:  griplab://state?<gripName>=<value>&...
//   - string-valued grips are stored verbatim (URL-encoded)
//   - structured grips (e.g. DiffEndpoint) are JSON-encoded
export interface LabState {
  view?: ViewId;
  file?: string | null;
  peerId?: string;
  diffLeft?: DiffEndpoint;
  diffRight?: DiffEndpoint;
  line?: number | null;
}

// Keys are the real grip ids so the URL is a literal grip/value map.
const KEY = {
  view: 'Lab.CurrentView',
  file: 'Lab.SelectedFile',
  peerId: 'Lab.SelectedPeerId',
  diffLeft: 'Lab.DiffLeft',
  diffRight: 'Lab.DiffRight',
  line: 'Lab.FocusLine',
} as const;

export const STATE_URL_PREFIX = 'griplab://state?';

export function buildStateUrl(state: LabState): string {
  const p = new URLSearchParams();
  if (state.view !== undefined) p.set(KEY.view, state.view);
  if (state.file) p.set(KEY.file, state.file);
  if (state.peerId !== undefined) p.set(KEY.peerId, state.peerId);
  if (state.diffLeft) p.set(KEY.diffLeft, JSON.stringify(state.diffLeft));
  if (state.diffRight) p.set(KEY.diffRight, JSON.stringify(state.diffRight));
  if (state.line != null) p.set(KEY.line, String(state.line));
  return STATE_URL_PREFIX + p.toString();
}

export function parseStateUrl(url: string): LabState {
  const query = url.slice(url.indexOf('?') + 1);
  const p = new URLSearchParams(query);
  const state: LabState = {};
  const view = p.get(KEY.view);
  if (view) state.view = view as ViewId;
  const file = p.get(KEY.file);
  if (file) state.file = file;
  const peer = p.get(KEY.peerId);
  if (peer) state.peerId = peer;
  const dl = p.get(KEY.diffLeft);
  if (dl) { try { state.diffLeft = JSON.parse(dl); } catch { /* ignore malformed */ } }
  const dr = p.get(KEY.diffRight);
  if (dr) { try { state.diffRight = JSON.parse(dr); } catch { /* ignore malformed */ } }
  const line = p.get(KEY.line);
  if (line) state.line = Number(line);
  return state;
}

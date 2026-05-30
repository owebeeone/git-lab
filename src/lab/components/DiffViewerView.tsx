import { useAtomValueTap, useGrip, useKeyedChildContext } from '@owebeeone/grip-react';
import {
  PEERS,
  SELECTED_FILE, SELECTED_FILE_TAP,
  DIFF_LEFT, DIFF_LEFT_TAP,
  DIFF_RIGHT, DIFF_RIGHT_TAP,
  DIFF_WINDOW, DIFF_WINDOW_TAP,
  ACTIVE_FILE, ACTIVE_FILE_TAP,
  FOCUS_LINE,
  WORKSPACE_TREE,
} from '../grips';
import { DIFF_DIAGNOSTICS, DIFF_HUNKS, DIFF_STREAM_STATUS } from '../grips.service';
import type { DiffEndpoint, FileRef, Peer } from '../types';
import { dragProps, fileLink, diffLineLink } from '../dnd';
import Avatar from './Avatar';

function splitKey(key: string): { repoPath: string; path: string } {
  const idx = key.indexOf('::');
  if (idx < 0) return { repoPath: '', path: key };
  return { repoPath: key.slice(0, idx), path: key.slice(idx + 2) };
}

function EndpointPicker({
  label, endpoint, onChange, peers,
}: {
  label: string;
  endpoint: DiffEndpoint;
  onChange: (e: DiffEndpoint) => void;
  peers: Peer[];
}) {
  return (
    <div className="endpoint-picker">
      <span className="ep-label">{label}</span>
      <Avatar peer={peers.find((p) => p.id === endpoint.peerId)} size={18} />
      <select value={endpoint.peerId} onChange={(e) => onChange({ ...endpoint, peerId: e.target.value })}>
        {peers.map((p) => <option key={p.id} value={p.id}>{p.name}{p.isSelf ? ' (you)' : ''}</option>)}
      </select>
      <select value={endpoint.ref} onChange={(e) => onChange({ ...endpoint, ref: e.target.value as FileRef })}>
        <option value="working">working</option>
        <option value="head">HEAD</option>
      </select>
    </div>
  );
}

export default function DiffViewerView() {
  const peers = useGrip(PEERS) ?? [];
  const selected = useGrip(SELECTED_FILE);
  const selectTap = useGrip(SELECTED_FILE_TAP);
  const left = useGrip(DIFF_LEFT) ?? DIFF_LEFT.defaultValue!;
  const leftTap = useGrip(DIFF_LEFT_TAP);
  const right = useGrip(DIFF_RIGHT) ?? DIFF_RIGHT.defaultValue!;
  const rightTap = useGrip(DIFF_RIGHT_TAP);
  const tree = useGrip(WORKSPACE_TREE) ?? [];

  const focusLine = useGrip(FOCUS_LINE) ?? null;

  const fileOptions = tree
    .filter((entry) => entry.kind === 'file')
    .map((entry) => ({ key: `${entry.repoPath}::${entry.path}`, repoPath: entry.repoPath, path: entry.path }));
  const activeFile = selected ?? fileOptions[0]?.key ?? '';
  const file = splitKey(activeFile);
  const ctx = useKeyedChildContext('diff:main');
  useAtomValueTap(ACTIVE_FILE, { ctx: ctx as never, initial: activeFile, tapGrip: ACTIVE_FILE_TAP });
  useAtomValueTap(DIFF_LEFT, { ctx: ctx as never, initial: left, tapGrip: DIFF_LEFT_TAP });
  useAtomValueTap(DIFF_RIGHT, { ctx: ctx as never, initial: right, tapGrip: DIFF_RIGHT_TAP });
  useAtomValueTap(DIFF_WINDOW, { ctx: ctx as never, initial: { lineStart: 0, lineEnd: 400 }, tapGrip: DIFF_WINDOW_TAP });

  const hunks = useGrip(DIFF_HUNKS, ctx) ?? [];
  const diagnostics = useGrip(DIFF_DIAGNOSTICS, ctx) ?? [];
  const streamStatus = useGrip(DIFF_STREAM_STATUS, ctx) ?? { status: 'idle', error: null };
  const rows = hunks.flatMap((hunk) => hunk.lines);
  const leftPeer = peers.find((p) => p.id === left.peerId);

  // Scroll the focused row into view when it mounts (ref callback, no effects).
  const scrollFocus = (el: HTMLDivElement | null) => {
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  };

  return (
    <section className="view">
      <div className="diff-controls">
        <select
          className="file-select"
          value={activeFile}
          onChange={(e) => selectTap?.set(e.target.value)}
        >
          {fileOptions.map((f) => <option key={f.key} value={f.key}>{f.repoPath}/{f.path}</option>)}
        </select>
        {/* Dragging a <select> is awkward, so this chip is the drag source. */}
        <span
          className="ref-chip"
          title="Drag to chat"
          {...dragProps(fileLink(file.repoPath, file.path, leftPeer))}
        >
          ⠿ share
        </span>
        <EndpointPicker label="Left" endpoint={left} onChange={(e) => leftTap?.set(e)} peers={peers} />
        <EndpointPicker label="Right" endpoint={right} onChange={(e) => rightTap?.set(e)} peers={peers} />
      </div>

      <div className="diff-table">
        {streamStatus.status === 'error' && <div className="diag-strip">{streamStatus.error}</div>}
        {diagnostics.map((diagnostic) => (
          <div className="diag-strip" key={`${diagnostic.code}:${diagnostic.endpoint ?? 'both'}`}>
            <strong>{diagnostic.code}</strong>
            <span>{diagnostic.message}</span>
          </div>
        ))}
        {rows.map((r, i) => {
          const isFocus = focusLine != null && (r.leftNo === focusLine || r.rightNo === focusLine);
          return (
            <div
              className={`diff-row ${r.kind}${isFocus ? ' focus' : ''}`}
              key={isFocus ? `focus-${focusLine}` : i}
              ref={isFocus ? scrollFocus : undefined}
            >
              <span
                className={`diff-no${r.leftNo != null ? ' line-handle' : ''}`}
                title={r.leftNo != null ? 'Drag this line to chat' : undefined}
                {...(r.leftNo != null ? dragProps(diffLineLink(file.repoPath, file.path, left, right, r.leftNo)) : {})}
              >
                {r.leftNo ?? ''}
              </span>
              <span className="diff-cell left">{r.left ?? ''}</span>
              <span
                className={`diff-no${r.rightNo != null ? ' line-handle' : ''}`}
                title={r.rightNo != null ? 'Drag this line to chat' : undefined}
                {...(r.rightNo != null ? dragProps(diffLineLink(file.repoPath, file.path, left, right, r.rightNo)) : {})}
              >
                {r.rightNo ?? ''}
              </span>
              <span className="diff-cell right">{r.right ?? ''}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

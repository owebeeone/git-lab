import { useGrip } from '@owebeeone/grip-react';
import {
  PEERS,
  SELECTED_FILE, SELECTED_FILE_TAP,
  DIFF_LEFT, DIFF_LEFT_TAP,
  DIFF_RIGHT, DIFF_RIGHT_TAP,
  FOCUS_LINE,
} from '../grips';
import { FILE_IMAGES } from '../fakeData';
import type { DiffEndpoint, FileImage, FileRef, Peer } from '../types';
import { lineDiff } from '../diff';
import { resolveContent } from '../content';
import { dragProps, fileLink, diffLineLink } from '../dnd';

function fileKey(f: FileImage) {
  return `${f.repoPath}::${f.path}`;
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

  const focusLine = useGrip(FOCUS_LINE) ?? null;

  const file = FILE_IMAGES.find((f) => fileKey(f) === selected) ?? FILE_IMAGES[0];
  const rows = lineDiff(
    resolveContent(file, left.peerId, left.ref, peers),
    resolveContent(file, right.peerId, right.ref, peers),
  );
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
          value={selected ?? fileKey(file)}
          onChange={(e) => selectTap?.set(e.target.value)}
        >
          {FILE_IMAGES.map((f) => <option key={fileKey(f)} value={fileKey(f)}>{f.repoPath}/{f.path}</option>)}
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

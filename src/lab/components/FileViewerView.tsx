import { useGrip, useChildContext, useAtomValueTap } from '@owebeeone/grip-react';
import { SELECTED_PEER_ID, PEERS, FOCUS_LINE, FILE_REF, FILE_REF_TAP } from '../grips';
import { FILE_IMAGES } from '../fakeData';
import type { EditorGroup, FileImage, FileRef, Peer } from '../types';
import { Highlighted } from '../highlight';
import { resolveContent } from '../content';
import { dragProps, fileLink, fileLineLink } from '../dnd';
import { useEditor } from '../useEditor';
import PeerSelect from './PeerSelect';
import FileExplorer from './FileExplorer';

function splitKey(key: string): { repoPath: string; path: string } {
  const idx = key.indexOf('::');
  return { repoPath: key.slice(0, idx), path: key.slice(idx + 2) };
}
function basename(path: string) {
  const parts = path.split('/');
  return parts[parts.length - 1];
}
function imageFor(key: string): FileImage | undefined {
  return FILE_IMAGES.find((f) => `${f.repoPath}::${f.path}` === key);
}
function newGroupId() {
  return `g-${Math.random().toString(36).slice(2, 7)}`;
}

// One editor column. Each column owns its own working/head selection via a
// per-instance child grip-context + atom tap (no shared global FILE_REF).
function EditorColumn(props: {
  group: EditorGroup;
  peers: Peer[];
  peerId: string;
  peer?: Peer;
  focusLine: number | null;
  isFocused: boolean;
  groupsCount: number;
  onFocusTab: (gid: string, key: string) => void;
  onCloseTab: (gid: string, key: string) => void;
  onSplit: () => void;
  onCloseGroup: (gid: string) => void;
  onFocusGroup: (group: EditorGroup) => void;
}) {
  const { group, peers, peerId, peer, focusLine, isFocused, groupsCount } = props;

  // View-specific FILE_REF: a child context with its own atom tap.
  // (useChildContext is typed GripContextLike; useAtomValueTap wants the
  // concrete GripContext, which isn't exported — the runtime value is correct.)
  const ctx = useChildContext();
  useAtomValueTap(FILE_REF, { ctx: ctx as never, initial: 'working', tapGrip: FILE_REF_TAP });
  const ref = useGrip(FILE_REF, ctx) ?? 'working';
  const refTap = useGrip(FILE_REF_TAP, ctx);

  const active = group.active;
  const info = active ? splitKey(active) : null;
  const img = active ? imageFor(active) : undefined;
  const code = active
    ? (img ? resolveContent(img, peerId, ref, peers) : `// ${info!.repoPath}/${info!.path}\n// (no preview available in the mock)\n`)
    : '';

  return (
    <div
      className={`editor-group${isFocused ? ' focused' : ''}`}
      onMouseDown={() => props.onFocusGroup(group)}
    >
      <div className="open-tabs">
        {group.open.length === 0 && <span className="muted otab-empty">No open files</span>}
        {group.open.map((k) => {
          const sp = splitKey(k);
          return (
            <div key={k} className={`otab${k === active ? ' active' : ''}`}>
              <button
                className="otab-name"
                {...dragProps(fileLink(sp.repoPath, sp.path, peer))}
                onClick={() => props.onFocusTab(group.id, k)}
                title={`${sp.repoPath}/${sp.path}`}
              >
                {basename(sp.path)}
              </button>
              <button className="otab-x" onClick={() => props.onCloseTab(group.id, k)} title="Close">×</button>
            </div>
          );
        })}
        <span className="otab-spacer" />
        <button className="otab-action" onClick={props.onSplit} title="Split editor">⫛</button>
        {groupsCount > 1 && (
          <button className="otab-action" onClick={() => props.onCloseGroup(group.id)} title="Close column">×</button>
        )}
      </div>
      <div className="editor">
        {active && info ? (
          <>
            <div className="file-bar">
              <span className="ref-chip" title="Drag to chat" {...dragProps(fileLink(info.repoPath, info.path, peer))}>
                ⠿ {info.repoPath}/{info.path}{peer && !peer.isSelf ? ` @${peer.name}` : ''}
              </span>
              <span className="spacer" />
              <div className="ref-toggle">
                {(['working', 'head'] as FileRef[]).map((r) => (
                  <button key={r} className={ref === r ? 'active' : ''} onClick={() => refTap?.set(r)}>{r}</button>
                ))}
              </div>
            </div>
            <Highlighted
              code={code}
              focusLine={isFocused ? focusLine : null}
              makeLineLink={(n) => fileLineLink(info.repoPath, info.path, peer, n)}
            />
          </>
        ) : (
          <div className="empty-editor">Select a file from the explorer to open it.</div>
        )}
      </div>
    </div>
  );
}

export default function FileViewerView() {
  const { groups, setGroups, activeGroup, activeGroupTap, selTap, openInFiles } = useEditor();
  const peerId = useGrip(SELECTED_PEER_ID) ?? '';
  const peers = useGrip(PEERS) ?? [];
  const peer = peers.find((p) => p.id === peerId);
  const focusLine = useGrip(FOCUS_LINE) ?? null;

  const focusedActive = groups.find((g) => g.id === activeGroup)?.active ?? null;

  const focusTab = (gid: string, key: string) => {
    setGroups(groups.map((g) => (g.id === gid ? { ...g, active: key } : g)));
    activeGroupTap?.set(gid);
    selTap?.set(key);
  };
  const closeTab = (gid: string, key: string) => {
    const next = groups.map((g) => {
      if (g.id !== gid) return g;
      const open = g.open.filter((k) => k !== key);
      const active = g.active === key ? (open.length ? open[open.length - 1] : null) : g.active;
      return { ...g, open, active };
    });
    setGroups(next);
    if (gid === activeGroup) selTap?.set(next.find((g) => g.id === gid)?.active ?? null);
  };
  const split = () => {
    const src = groups.find((g) => g.id === activeGroup);
    const id = newGroupId();
    const ng: EditorGroup = { id, open: src?.active ? [src.active] : [], active: src?.active ?? null };
    setGroups([...groups, ng]);
    activeGroupTap?.set(id);
  };
  const closeGroup = (gid: string) => {
    if (groups.length <= 1) return;
    const rest = groups.filter((g) => g.id !== gid);
    setGroups(rest);
    if (activeGroup === gid) {
      activeGroupTap?.set(rest[0].id);
      selTap?.set(rest[0].active ?? null);
    }
  };
  const focusGroup = (group: EditorGroup) => {
    if (group.id !== activeGroup) {
      activeGroupTap?.set(group.id);
      if (group.active) selTap?.set(group.active);
    }
  };

  return (
    <section className="view files-ide">
      <div className="ide-body">
        <FileExplorer activeKey={focusedActive} onOpen={openInFiles} peer={peer} />
        <div className="editor-stack">
          <div className="files-toolbar"><PeerSelect /></div>
          <div className="editor-groups">
            {groups.map((g) => (
              <EditorColumn
                key={g.id}
                group={g}
                peers={peers}
                peerId={peerId}
                peer={peer}
                focusLine={focusLine}
                isFocused={g.id === activeGroup}
                groupsCount={groups.length}
                onFocusTab={focusTab}
                onCloseTab={closeTab}
                onSplit={split}
                onCloseGroup={closeGroup}
                onFocusGroup={focusGroup}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

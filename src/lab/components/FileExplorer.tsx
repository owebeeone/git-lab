import { useGrip } from '@owebeeone/grip-react';
import { WORKSPACE_FILES } from '../fakeData';
import {
  EXPLORER_COLLAPSED, EXPLORER_COLLAPSED_TAP,
  EXPLORER_OPEN, EXPLORER_OPEN_TAP,
  EXPLORER_WIDTH, EXPLORER_WIDTH_TAP,
  EXPLORER_DRAG, EXPLORER_DRAG_TAP,
} from '../grips';
import type { Peer } from '../types';
import { dragProps, fileLink } from '../dnd';
import { Icon } from './icons';

const MIN_W = 160;
const MAX_W = 480;

interface TNode {
  name: string;
  kind: 'dir' | 'file';
  repoPath: string;
  path?: string; // for files
  children: Map<string, TNode>;
}

function buildTree(): TNode {
  const root: TNode = { name: '', kind: 'dir', repoPath: '', children: new Map() };
  for (const { repoPath, path } of WORKSPACE_FILES) {
    const repoName = repoPath || 'root';
    let repoNode = root.children.get(repoName);
    if (!repoNode) {
      repoNode = { name: repoName, kind: 'dir', repoPath, children: new Map() };
      root.children.set(repoName, repoNode);
    }
    const segs = path.split('/');
    let cur = repoNode;
    segs.forEach((seg, i) => {
      const isFile = i === segs.length - 1;
      let child = cur.children.get(seg);
      if (!child) {
        child = { name: seg, kind: isFile ? 'file' : 'dir', repoPath, path: isFile ? path : undefined, children: new Map() };
        cur.children.set(seg, child);
      }
      cur = child;
    });
  }
  return root;
}

export default function FileExplorer({
  activeKey, onOpen, peer,
}: {
  activeKey: string | null | undefined;
  onOpen: (key: string) => void;
  peer?: Peer;
}) {
  const tree = buildTree();
  const collapsedList = useGrip(EXPLORER_COLLAPSED) ?? [];
  const collapsedTap = useGrip(EXPLORER_COLLAPSED_TAP);
  const collapsed = new Set(collapsedList);

  const open = useGrip(EXPLORER_OPEN) ?? true;
  const openTap = useGrip(EXPLORER_OPEN_TAP);
  const width = useGrip(EXPLORER_WIDTH) ?? 240;
  const widthTap = useGrip(EXPLORER_WIDTH_TAP);
  const drag = useGrip(EXPLORER_DRAG) ?? null;
  const dragTap = useGrip(EXPLORER_DRAG_TAP);

  const toggle = (id: string) => {
    collapsedTap?.set(collapsed.has(id) ? collapsedList.filter((x) => x !== id) : [...collapsedList, id]);
  };

  const renderNode = (node: TNode, depth: number, idPath: string) => {
    const id = `${node.repoPath}/${idPath}`;
    if (node.kind === 'file') {
      const key = `${node.repoPath}::${node.path}`;
      return (
        <button
          key={id}
          className={`tree-row file${activeKey === key ? ' active' : ''}`}
          style={{ paddingLeft: 8 + depth * 14 }}
          title="Click to open · drag to chat"
          {...dragProps(fileLink(node.repoPath, node.path!, peer))}
          onClick={() => onOpen(key)}
        >
          <Icon name="file" size={14} />
          <span>{node.name}</span>
        </button>
      );
    }
    const isOpen = !collapsed.has(id);
    const kids = [...node.children.values()].sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === 'dir' ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    return (
      <div key={id}>
        <button
          className="tree-row dir"
          style={{ paddingLeft: 8 + depth * 14 }}
          onClick={() => toggle(id)}
        >
          <span className={`tree-caret${isOpen ? ' open' : ''}`}><Icon name="chevron" size={12} /></span>
          <Icon name="folder" size={14} />
          <span>{node.name}</span>
        </button>
        {isOpen && kids.map((k) => renderNode(k, depth + 1, `${idPath}/${k.name}`))}
      </div>
    );
  };

  const repos = [...tree.children.values()].sort((a, b) => a.name.localeCompare(b.name));

  if (!open) {
    return (
      <button className="explorer-collapsed-tab" onClick={() => openTap?.set(true)} title="Show explorer">
        ‹ Explorer
      </button>
    );
  }

  return (
    <>
      {drag && (
        <div
          className="drag-overlay col"
          onMouseMove={(e) => widthTap?.set(Math.max(MIN_W, Math.min(MAX_W, drag.startSize + (e.clientX - drag.start))))}
          onMouseUp={() => dragTap?.set(null)}
        />
      )}
      <aside className="explorer" style={{ width }}>
        <div className="explorer-head">
          <span>Explorer</span>
          <button className="ghost explorer-collapse" onClick={() => openTap?.set(false)} title="Hide explorer">‹</button>
        </div>
        <div className="explorer-tree">
          {repos.map((r) => renderNode(r, 0, r.name))}
        </div>
      </aside>
      <div className="explorer-resizer" onMouseDown={(e) => dragTap?.set({ start: e.clientX, startSize: width })} title="Drag to resize" />
    </>
  );
}

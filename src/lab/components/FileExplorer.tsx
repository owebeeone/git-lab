import { useGrip } from '@owebeeone/grip-react';
import {
  EXPLORER_COLLAPSED, EXPLORER_COLLAPSED_TAP,
  EXPLORER_OPEN, EXPLORER_OPEN_TAP,
  EXPLORER_WIDTH, EXPLORER_WIDTH_TAP,
  EXPLORER_DRAG, EXPLORER_DRAG_TAP,
  SELECTED_PEER_ID,
  WORKSPACE_REPOS,
  WORKSPACE_TREE,
  WORKSPACE_TREE_STATUS,
} from '../grips';
import type { FileChangeKind, Peer, RepoStatus, WorkspaceTreeEntry } from '../types';
import { dragProps, fileLink } from '../dnd';
import { Icon } from './icons';

const MIN_W = 160;
const MAX_W = 480;

interface TNode {
  name: string;
  kind: 'dir' | 'file';
  repoPath: string;
  fullPath: string;
  path?: string; // for files
  gitStatus: TreeGitStatus;
  children: Map<string, TNode>;
}

type TreeGitStatus = 'clean' | 'dirty' | 'untracked' | 'ignored';

function buildTree(entries: WorkspaceTreeEntry[], repos: RepoStatus[]): TNode {
  const statusMap = buildStatusMap(repos);
  const root: TNode = { name: 'root', kind: 'dir', repoPath: '', fullPath: '', gitStatus: 'clean', children: new Map() };
  for (const { repoPath, path, kind } of entries) {
    if (kind !== 'file') continue;
    const fullPath = joinPath(repoPath, path);
    const segs = fullPath.split('/').filter(Boolean);
    let cur = root;
    segs.forEach((seg, i) => {
      const isFile = i === segs.length - 1;
      let child = cur.children.get(seg);
      const childFullPath = joinPath(cur.fullPath, seg);
      if (!child) {
        child = {
          name: seg,
          kind: isFile ? 'file' : 'dir',
          repoPath: isFile ? repoPath : '',
          fullPath: childFullPath,
          path: isFile ? path : undefined,
          gitStatus: 'clean',
          children: new Map(),
        };
        cur.children.set(seg, child);
      }
      if (isFile) {
        child.repoPath = repoPath;
        child.path = path;
        child.gitStatus = statusForChange(
          statusMap.get(statusKey(repoPath, path))
            ?? statusMap.get(statusKey('', fullPath)),
        );
      }
      cur = child;
    });
  }
  applyDeletedStatuses(root, repos);
  updateFolderStatuses(root);
  return root;
}

function buildStatusMap(repos: RepoStatus[]): Map<string, FileChangeKind> {
  const map = new Map<string, FileChangeKind>();
  for (const repo of repos) {
    for (const file of repo.changedFiles) {
      const fullPath = joinPath(repo.path, file.path);
      map.set(statusKey(repo.path, file.path), file.change);
      map.set(statusKey('', fullPath), file.change);
    }
  }
  return map;
}

function applyDeletedStatuses(root: TNode, repos: RepoStatus[]) {
  for (const repo of repos) {
    for (const file of repo.changedFiles) {
      if (file.change !== 'deleted') continue;
      const fullPath = joinPath(repo.path, file.path);
      const dirPath = fullPath.split('/').slice(0, -1);
      let cur = root;
      for (const seg of dirPath) {
        const next = cur.children.get(seg);
        if (!next) break;
        cur = next;
        cur.gitStatus = mergeStatus(cur.gitStatus, 'dirty');
      }
    }
  }
}

function updateFolderStatuses(node: TNode): TreeGitStatus {
  if (node.kind === 'file') return node.gitStatus;
  let status = node.gitStatus;
  for (const child of node.children.values()) {
    status = mergeStatus(status, updateFolderStatuses(child));
  }
  node.gitStatus = status;
  return status;
}

function statusForChange(change: FileChangeKind | undefined): TreeGitStatus {
  if (change === 'untracked') return 'untracked';
  if (change === 'ignored') return 'ignored';
  if (change) return 'dirty';
  return 'clean';
}

function mergeStatus(a: TreeGitStatus, b: TreeGitStatus): TreeGitStatus {
  return statusRank(b) > statusRank(a) ? b : a;
}

function statusRank(status: TreeGitStatus): number {
  if (status === 'untracked') return 3;
  if (status === 'dirty') return 2;
  if (status === 'ignored') return 1;
  return 0;
}

function statusKey(repoPath: string, path: string): string {
  return `${repoPath}::${path}`;
}

function joinPath(...parts: string[]): string {
  return parts.filter(Boolean).join('/');
}

export default function FileExplorer({
  activeKey, onOpen, peer,
}: {
  activeKey: string | null | undefined;
  onOpen: (key: string) => void;
  peer?: Peer;
}) {
  const selectedPeerId = useGrip(SELECTED_PEER_ID) ?? '';
  const treeStatus = useGrip(WORKSPACE_TREE_STATUS) ?? { peerId: '', status: 'idle' as const, error: null };
  const rawTree = useGrip(WORKSPACE_TREE) ?? [];
  const repos = useGrip(WORKSPACE_REPOS) ?? [];
  const statusMatchesPeer = treeStatus.peerId === selectedPeerId;
  const initialSnapshotReady = treeStatus.status === 'idle' && rawTree.length > 0;
  const treeReadyForPeer = (statusMatchesPeer && treeStatus.status === 'ready') || initialSnapshotReady;
  const loadingTree = statusMatchesPeer && treeStatus.status === 'loading';
  const tree = buildTree(treeReadyForPeer ? rawTree : [], repos);
  const collapsedToggleList = useGrip(EXPLORER_COLLAPSED) ?? [];
  const collapsedTap = useGrip(EXPLORER_COLLAPSED_TAP);
  const collapsedToggles = new Set(collapsedToggleList);

  const open = useGrip(EXPLORER_OPEN) ?? true;
  const openTap = useGrip(EXPLORER_OPEN_TAP);
  const width = useGrip(EXPLORER_WIDTH) ?? 240;
  const widthTap = useGrip(EXPLORER_WIDTH_TAP);
  const drag = useGrip(EXPLORER_DRAG) ?? null;
  const dragTap = useGrip(EXPLORER_DRAG_TAP);

  const toggle = (id: string) => {
    collapsedTap?.set(
      collapsedToggles.has(id)
        ? collapsedToggleList.filter((x) => x !== id)
        : [...collapsedToggleList, id],
    );
  };

  const defaultOpen = (node: TNode, depth: number) => depth === 0 && node.name === 'root';

  const isNodeOpen = (node: TNode, depth: number, id: string) => {
    const openByDefault = defaultOpen(node, depth);
    return collapsedToggles.has(id) ? !openByDefault : openByDefault;
  };

  const renderNode = (node: TNode, depth: number, idPath: string) => {
    const id = node.fullPath || idPath;
    if (node.kind === 'file') {
      const key = `${node.repoPath}::${node.path}`;
      return (
        <button
          key={id}
          className={`tree-row file status-${node.gitStatus}${activeKey === key ? ' active' : ''}`}
          style={{ paddingLeft: 8 + depth * 14 }}
          title={`${node.gitStatus} · click to open · drag to chat`}
          {...dragProps(fileLink(node.repoPath, node.path!, peer))}
          onClick={() => onOpen(key)}
        >
          <Icon name="file" size={14} />
          <span className={`tree-status-dot ${node.gitStatus}`} />
          <span>{node.name}</span>
        </button>
      );
    }
    const isOpen = isNodeOpen(node, depth, id);
    const kids = [...node.children.values()].sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === 'dir' ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    return (
      <div key={id}>
        <button
          className={`tree-row dir status-${node.gitStatus}`}
          style={{ paddingLeft: 8 + depth * 14 }}
          onClick={() => toggle(id)}
          title={node.gitStatus}
        >
          <span className={`tree-caret${isOpen ? ' open' : ''}`}><Icon name="chevron" size={12} /></span>
          <Icon name="folder" size={14} />
          <span className={`tree-status-dot ${node.gitStatus}`} />
          <span>{node.name}</span>
        </button>
        {isOpen && kids.map((k) => renderNode(k, depth + 1, `${idPath}/${k.name}`))}
      </div>
    );
  };

  const rootNodes = tree.children.size > 0 ? [tree] : [];
  const peerName = peer?.name ?? selectedPeerId;

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
          <span className={`explorer-state ${loadingTree ? 'loading' : treeReadyForPeer ? 'ready' : 'idle'}`}>
            {loadingTree ? `Loading ${peerName}` : treeReadyForPeer ? `${rawTree.length} files` : 'Waiting'}
          </span>
          <button className="ghost explorer-collapse" onClick={() => openTap?.set(false)} title="Hide explorer">‹</button>
        </div>
        <div className="explorer-tree">
          {loadingTree && (
            <div className="tree-loading">
              <span className="mini-spinner" />
              <span>Loading file tree for {peerName}…</span>
            </div>
          )}
          {!loadingTree && !treeReadyForPeer && (
            <div className="tree-loading muted">
              <span>Waiting for file tree…</span>
            </div>
          )}
          {treeReadyForPeer && rootNodes.length === 0 && (
            <div className="tree-loading muted">
              <span>No files found.</span>
            </div>
          )}
          {rootNodes.map((r) => renderNode(r, 0, r.name))}
        </div>
      </aside>
      <div className="explorer-resizer" onMouseDown={(e) => dragTap?.set({ start: e.clientX, startSize: width })} title="Drag to resize" />
    </>
  );
}

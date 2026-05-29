import { useGrip } from '@owebeeone/grip-react';
import {
  SELECTED_PEER_ID,
  PEERS,
  CURRENT_VIEW_TAP,
  WORKSPACE_LAYOUT,
  WORKSPACE_LAYOUT_TAP,
  WORKSPACE_MENU,
  WORKSPACE_MENU_TAP,
} from '../grips';
import { REPO_STATUS_BY_PEER } from '../fakeData';
import type { Peer, RepoStatus } from '../types';
import { dragProps, fileLink } from '../dnd';
import { useEditor } from '../useEditor';
import PeerTabs from './PeerTabs';
import WorkspaceGraphView from './WorkspaceGraphView';

const CHANGE_BADGE: Record<string, string> = {
  modified: 'M', added: 'A', deleted: 'D', untracked: '?', renamed: 'R',
};

function RepoCard({ repo, peer }: { repo: RepoStatus; peer?: Peer }) {
  const repoKey = repo.path || 'root';
  const openMenu = useGrip(WORKSPACE_MENU) ?? null;
  const menuTap = useGrip(WORKSPACE_MENU_TAP);
  const menuOpen = openMenu === repoKey;
  const setMenuOpen = (v: boolean) => menuTap?.set(v ? repoKey : null);
  const viewTap = useGrip(CURRENT_VIEW_TAP);
  const { openInFiles } = useEditor();

  return (
    <div className="repo-card">
      <div className="repo-head">
        <div className="repo-title">
          <strong>{repo.name}</strong>
          {repo.path && <span className="repo-path">{repo.path}</span>}
        </div>
        <div className="repo-tools">
          <button className="ghost" onClick={() => setMenuOpen(!menuOpen)}>⋯</button>
          {menuOpen && (
            <div className="menu" onMouseLeave={() => setMenuOpen(false)}>
              <button onClick={() => { viewTap?.set('file'); setMenuOpen(false); }}>View files</button>
              <button onClick={() => { viewTap?.set('diff'); setMenuOpen(false); }}>Diff vs peer</button>
              <button onClick={() => setMenuOpen(false)}>Run command…</button>
            </div>
          )}
        </div>
      </div>
      <div className="repo-meta">
        <span className="branch">⎇ {repo.branch}</span>
        <span className="sha">{repo.head}</span>
        {repo.ahead > 0 && <span className="ahead">↑{repo.ahead}</span>}
        {repo.behind > 0 && <span className="behind">↓{repo.behind}</span>}
        <span className={`state ${repo.dirty ? 'dirty' : 'clean'}`}>
          {repo.dirty ? 'dirty' : 'clean'}
        </span>
      </div>
      {repo.changedFiles.length > 0 && (
        <ul className="changed-files">
          {repo.changedFiles.map((f) => (
            <li key={f.path}>
              <button
                className="file-link"
                title="Click to open · drag to chat"
                {...dragProps(fileLink(repo.path, f.path, peer))}
                onClick={() => openInFiles(`${repo.path}::${f.path}`)}
              >
                <span className={`chg ${f.change}`}>{CHANGE_BADGE[f.change]}</span>
                {f.path}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function WorkspaceStatusView() {
  const peerId = useGrip(SELECTED_PEER_ID) ?? '';
  const peers = useGrip(PEERS) ?? [];
  const peer = peers.find((p) => p.id === peerId);
  const repos = REPO_STATUS_BY_PEER[peerId] ?? [];
  const layout = useGrip(WORKSPACE_LAYOUT) ?? 'tiles';
  const layoutTap = useGrip(WORKSPACE_LAYOUT_TAP);

  return (
    <section className="view">
      <div className="view-head-row">
        <PeerTabs />
        <div className="segmented">
          <button className={layout === 'tiles' ? 'active' : ''} onClick={() => layoutTap?.set('tiles')}>Tiles</button>
          <button className={layout === 'graph' ? 'active' : ''} onClick={() => layoutTap?.set('graph')}>Graph</button>
        </div>
      </div>
      {layout === 'graph' ? (
        <WorkspaceGraphView repos={repos} peer={peer} />
      ) : (
        <div className="repo-grid">
          {repos.map((r) => <RepoCard key={r.path || 'root'} repo={r} peer={peer} />)}
        </div>
      )}
    </section>
  );
}

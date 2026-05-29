import { useGrip } from '@owebeeone/grip-react';
import {
  SESSIONS, SESSIONS_TAP,
  SELECTED_SESSION, SELECTED_SESSION_TAP,
  SELECTED_TARGET, SELECTED_TARGET_TAP,
  SESSION_SEARCH, SESSION_SEARCH_TAP,
  SESSION_FILTER, SESSION_FILTER_TAP,
  SESSION_DRAFT, SESSION_DRAFT_TAP,
  RUN_REPOS, RUN_REPOS_TAP, RUN_REPOS_OPEN, RUN_REPOS_OPEN_TAP,
  PURGE_DAYS, PURGE_DAYS_TAP,
  SESSION_OUTPUT, SESSION_DIAGNOSTICS,
  PEERS, SELECTED_PEER_ID, THEME,
} from '../grips';
import { REPO_STATUS_BY_PEER } from '../fakeData';
import type { CommandSession, RepoRun, SessionStatusFilter } from '../types';
import { createTerminal } from '../terminalController';
import PeerSelect from './PeerSelect';

const FILTERS: { id: SessionStatusFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'errors', label: 'Errors' },
  { id: 'running', label: 'Running' },
  { id: 'hidden', label: 'Hidden' },
];
const DAY_MS = 86400000;

type Status = 'running' | 'ok' | 'error';

function targetStatus(t: RepoRun): Status {
  if (t.exitCode == null) return 'running';
  return t.exitCode === 0 ? 'ok' : 'error';
}
// Aggregate: running if any still running, else error if any failed, else ok.
function sessionStatus(s: CommandSession): Status {
  const sts = s.targets.map(targetStatus);
  if (sts.includes('running')) return 'running';
  if (sts.includes('error')) return 'error';
  return 'ok';
}
function repoLabel(p: string) { return p || 'root'; }
function fmtTime(ts: number) { return new Date(ts).toLocaleTimeString(); }
function fmtDur(ms?: number) { return ms == null ? '' : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`; }

function TerminalPane({ termKey, content, interactive, dark }: { termKey: string; content: string; interactive: boolean; dark: boolean }) {
  return (
    <div
      key={termKey}
      className="xterm-host"
      ref={(el) => {
        if (!el) return;
        const h = createTerminal(el, { content, interactive, dark });
        return () => h.dispose();
      }}
    />
  );
}

export default function SessionsView() {
  const sessions = useGrip(SESSIONS) ?? [];
  const sessionsTap = useGrip(SESSIONS_TAP);
  const selected = useGrip(SELECTED_SESSION) ?? null;
  const selectedTap = useGrip(SELECTED_SESSION_TAP);
  const selectedTarget = useGrip(SELECTED_TARGET) ?? null;
  const selectedTargetTap = useGrip(SELECTED_TARGET_TAP);
  const search = useGrip(SESSION_SEARCH) ?? '';
  const searchTap = useGrip(SESSION_SEARCH_TAP);
  const filter = useGrip(SESSION_FILTER) ?? 'all';
  const filterTap = useGrip(SESSION_FILTER_TAP);
  const draft = useGrip(SESSION_DRAFT) ?? '';
  const draftTap = useGrip(SESSION_DRAFT_TAP);
  const runRepos = useGrip(RUN_REPOS) ?? [''];
  const runReposTap = useGrip(RUN_REPOS_TAP);
  const reposOpen = useGrip(RUN_REPOS_OPEN) ?? false;
  const reposOpenTap = useGrip(RUN_REPOS_OPEN_TAP);
  const purgeDays = useGrip(PURGE_DAYS) ?? 7;
  const purgeDaysTap = useGrip(PURGE_DAYS_TAP);
  const output = useGrip(SESSION_OUTPUT) ?? '';
  const diag = useGrip(SESSION_DIAGNOSTICS) ?? { kind: 'none', failed: 0, passed: 0, failures: [] };
  const peers = useGrip(PEERS) ?? [];
  const targetPeer = useGrip(SELECTED_PEER_ID) ?? '';
  const theme = useGrip(THEME) ?? 'dark';

  const nameOf = (id: string) => peers.find((p) => p.id === id)?.name ?? id;
  const availableRepos = REPO_STATUS_BY_PEER[targetPeer] ?? [];

  const hiddenCount = sessions.filter((s) => s.hidden).length;
  const q = search.trim().toLowerCase();
  const visible = sessions.filter((s) => {
    if (filter === 'hidden') { if (!s.hidden) return false; }
    else if (s.hidden) return false; // hidden sessions only show under the Hidden filter
    const st = sessionStatus(s);
    if (filter === 'errors' && st !== 'error') return false;
    if (filter === 'running' && st !== 'running') return false;
    if (!q) return true;
    return s.argv.join(' ').toLowerCase().includes(q) || s.targets.some((t) => t.output.toLowerCase().includes(q));
  });

  const current = sessions.find((s) => s.id === selected) ?? null;
  const activeTarget = current
    ? (current.targets.find((t) => t.repoPath === selectedTarget) ?? current.targets[0])
    : null;

  const toggleRepo = (repoPath: string) => {
    runReposTap?.set(runRepos.includes(repoPath) ? runRepos.filter((r) => r !== repoPath) : [...runRepos, repoPath]);
  };

  const runCommand = () => {
    const cmd = draft.trim();
    if (!cmd) return;
    const repos = runRepos.length ? runRepos : [''];
    const ts = Date.now();
    const targets: RepoRun[] = repos.map((repoPath) => ({
      repoPath,
      exitCode: 0,
      durationMs: 0,
      output: `$ ${cmd}\n\u001b[2m(mock) ran in ${repoLabel(repoPath)} on ${nameOf(targetPeer)}\u001b[0m\n`,
    }));
    const session: CommandSession = { id: `sess-${ts}`, peerId: targetPeer, argv: cmd.split(/\s+/), startedAt: ts, targets };
    sessionsTap?.set([session, ...sessions]);
    selectedTap?.set(session.id);
    selectedTargetTap?.set(targets[0].repoPath);
    draftTap?.set('');
  };

  const openTerminal = () => {
    const ts = Date.now();
    const session: CommandSession = {
      id: `term-${ts}`,
      peerId: targetPeer,
      argv: ['bash', '-l'],
      startedAt: ts,
      interactive: true,
      targets: [{ repoPath: '', exitCode: null, output: '' }],
    };
    sessionsTap?.set([session, ...sessions]);
    selectedTap?.set(session.id);
    selectedTargetTap?.set('');
  };

  const setHidden = (id: string, hidden: boolean) => {
    sessionsTap?.set(sessions.map((s) => (s.id === id ? { ...s, hidden } : s)));
    // When hiding the selected session (and not browsing Hidden), move selection on.
    if (hidden && selected === id && filter !== 'hidden') {
      const nextSel = sessions.find((s) => s.id !== id && !s.hidden);
      selectedTap?.set(nextSel?.id ?? null);
    }
  };

  const purge = () => {
    const cutoff = Date.now() - purgeDays * DAY_MS;
    const next = sessions.filter((s) => s.startedAt >= cutoff);
    sessionsTap?.set(next);
    if (selected && !next.some((s) => s.id === selected)) selectedTap?.set(next[0]?.id ?? null);
  };

  return (
    <section className="view sessions-view">
      <div className="sessions-toolbar">
        <input
          className="session-search"
          placeholder="Search commands + output…"
          value={search}
          onChange={(e) => searchTap?.set(e.target.value)}
        />
        <div className="segmented">
          {FILTERS.map((f) => (
            <button key={f.id} className={filter === f.id ? 'active' : ''} onClick={() => filterTap?.set(f.id)}>{f.label}</button>
          ))}
        </div>
        <span className="spacer" />
        <PeerSelect />
        {/* repo multi-select */}
        <div className="repo-multi">
          <button className="repo-multi-btn" onClick={() => reposOpenTap?.set(!reposOpen)}>
            {runRepos.length} repo{runRepos.length === 1 ? '' : 's'} ▾
          </button>
          {reposOpen && (
            <>
              <div className="repo-multi-backdrop" onClick={() => reposOpenTap?.set(false)} />
              <div className="repo-multi-panel">
                {availableRepos.map((r) => (
                  <label key={r.path || 'root'} className="repo-multi-item">
                    <input type="checkbox" checked={runRepos.includes(r.path)} onChange={() => toggleRepo(r.path)} />
                    {r.name}<span className="muted"> {r.path || 'root'}</span>
                  </label>
                ))}
              </div>
            </>
          )}
        </div>
        <input
          className="session-cmd"
          placeholder="command to run (e.g. uv run pytest -q)"
          value={draft}
          onChange={(e) => draftTap?.set(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') runCommand(); }}
        />
        <button className="primary" onClick={runCommand}>Run</button>
        <button className="ghost" onClick={openTerminal}>▶ Terminal</button>
      </div>

      <div className="sessions-body">
        <div className="session-col">
        <ul className="session-list">
          {visible.length === 0 && <li className="muted session-empty">No sessions match.</li>}
          {visible.map((s) => {
            const st = sessionStatus(s);
            return (
              <li key={s.id}>
                <button
                  className={`session-row${s.id === selected ? ' active' : ''}`}
                  onClick={() => { selectedTap?.set(s.id); selectedTargetTap?.set(s.targets[0].repoPath); }}
                >
                  <span className={`session-dot ${st}`} />
                  <span className="session-cmdtext">{s.interactive ? 'terminal' : s.argv.join(' ')}</span>
                  <span className="session-sub">
                    {nameOf(s.peerId)} · {fmtTime(s.startedAt)}
                    {s.targets.length > 1 ? ` · ${s.targets.length} repos` : ` · ${repoLabel(s.targets[0].repoPath)}`}
                  </span>
                  {s.targets.length > 1 && (
                    <span className="session-targets">
                      {s.targets.map((t) => <span key={t.repoPath || 'root'} className={`mini-dot ${targetStatus(t)}`} title={repoLabel(t.repoPath)} />)}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
        <div className="session-footer">
          <span className="muted">{visible.length} shown · {hiddenCount} hidden</span>
          <span className="spacer" />
          <label className="purge-ctl">
            purge &gt;{' '}
            <input
              type="number"
              min={0}
              value={purgeDays}
              onChange={(e) => purgeDaysTap?.set(Math.max(0, Number(e.target.value) || 0))}
            />{' '}d
          </label>
          <button className="ghost" onClick={purge} title="Permanently remove sessions older than N days">Purge</button>
        </div>
        </div>

        <div className="session-detail">
          {current && activeTarget ? (
            <>
              <div className="session-head">
                <div className="session-argv">{current.interactive ? `terminal · ${current.argv.join(' ')}` : current.argv.join(' ')}</div>
                <div className="session-meta">{nameOf(current.peerId)} · {fmtTime(current.startedAt)}</div>
                <span className="spacer" />
                {current.hidden
                  ? <button className="ghost" onClick={() => setHidden(current.id, false)} title="Unhide session">unhide</button>
                  : <button className="ghost" onClick={() => setHidden(current.id, true)} title="Hide session">hide</button>}
              </div>

              {/* per-repo target selector */}
              {current.targets.length > 1 && (
                <div className="target-tabs">
                  {current.targets.map((t) => {
                    const ts = targetStatus(t);
                    return (
                      <button
                        key={t.repoPath || 'root'}
                        className={`target-tab${t.repoPath === activeTarget.repoPath ? ' active' : ''}`}
                        onClick={() => selectedTargetTap?.set(t.repoPath)}
                      >
                        <span className={`mini-dot ${ts}`} />
                        {repoLabel(t.repoPath)}
                        {t.exitCode != null && t.exitCode !== 0 ? <span className="muted"> exit {t.exitCode}</span> : ''}
                      </button>
                    );
                  })}
                </div>
              )}

              <div className="session-substatus">
                <span className={`state ${targetStatus(activeTarget) === 'error' ? 'dirty' : 'clean'}`}>
                  {targetStatus(activeTarget) === 'running' ? 'running' : targetStatus(activeTarget) === 'ok' ? 'ok' : `exit ${activeTarget.exitCode}`}
                </span>
                <span className="muted">{repoLabel(activeTarget.repoPath)}{activeTarget.durationMs ? ` · ${fmtDur(activeTarget.durationMs)}` : ''}</span>
              </div>

              {(diag.failed > 0 || diag.failures.length > 0) && (
                <div className="diag-strip">
                  <strong className="diag-count">{diag.failed} failed</strong>
                  {diag.passed > 0 && <span className="muted"> · {diag.passed} passed</span>}
                  {diag.failures.slice(0, 4).map((f, i) => (
                    <span key={i} className="diag-failure" title={f}>{f.split(' - ')[0].split('::').pop()}</span>
                  ))}
                </div>
              )}

              <TerminalPane
                termKey={`${current.id}::${activeTarget.repoPath}`}
                content={output}
                interactive={!!current.interactive}
                dark={theme === 'dark'}
              />
            </>
          ) : (
            <div className="empty-editor">Select a session, run a command, or open a terminal.</div>
          )}
        </div>
      </div>
    </section>
  );
}

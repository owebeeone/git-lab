import { useGrip } from '@owebeeone/grip-react';
import {
  SESSIONS, SESSIONS_TAP,
  SELECTED_SESSION, SELECTED_SESSION_TAP,
  SELECTED_TARGET, SELECTED_TARGET_TAP,
  SELECTED_PEER_ID_TAP,
  SESSION_SEARCH, SESSION_SEARCH_TAP,
  SESSION_FILTERS, SESSION_FILTERS_TAP,
  SESSION_DRAFT, SESSION_DRAFT_TAP,
  RUN_REPOS, RUN_REPOS_TAP,
  PURGE_DAYS, PURGE_DAYS_TAP,
  RUN_DIALOG_OPEN, RUN_DIALOG_OPEN_TAP,
  SESSION_OUTPUT, SESSION_DIAGNOSTICS,
  PEERS, SELECTED_PEER_ID, THEME,
  WORKSPACE_REPOS,
} from '../grips';
import type { CommandSession, RepoRun, SessionFilterMod } from '../types';
import { createTerminal } from '../terminalController';
import { LAB_SERVICE_MODE } from '../dataMode';
import { openServiceTerminal, resizeServiceTerminal, runServiceCommand, sendServiceTerminalInput } from '../serviceClient/commands';
import PeerSelect from './PeerSelect';
import Avatar from './Avatar';

// Independent filter modifiers (toggle on/off, compose together).
const FILTERS: { id: SessionFilterMod; label: string }[] = [
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

// Lightweight "does this command make sense?" check for the run dialog.
function validateCommand(cmd: string, repoCount: number): { errors: string[]; warnings: string[]; argv: string[] } {
  const errors: string[] = [];
  const warnings: string[] = [];
  const trimmed = cmd.trim();
  const argv = trimmed ? trimmed.split(/\s+/) : [];
  if (!trimmed) errors.push('Enter a command to run.');
  if (repoCount === 0) errors.push('Select at least one repo.');
  if (/\brm\s+-rf?\b/.test(trimmed) || /\bsudo\b/.test(trimmed) || /:\(\)\s*\{.*\};\s*:/.test(trimmed) || />\s*\/dev\/sd/.test(trimmed)) {
    warnings.push('Looks potentially destructive — double-check before running.');
  }
  if (trimmed && /^[A-Z_]+=/.test(trimmed)) {
    warnings.push('Starts with an env assignment; the runner executes a program, not a shell line.');
  }
  return { errors, warnings, argv };
}

function TerminalPane({
  termKey, content, interactive, dark, sessionId, peerId,
}: {
  termKey: string;
  content: string;
  interactive: boolean;
  dark: boolean;
  sessionId?: string;
  peerId?: string;
}) {
  return (
    <div
      key={termKey}
      className="xterm-host"
      ref={(el) => {
        if (!el) return;
        const h = createTerminal(el, {
          content,
          interactive,
          dark,
          onData: LAB_SERVICE_MODE && sessionId && peerId ? (data) => { void sendServiceTerminalInput(sessionId, data, peerId); } : undefined,
          onResize: LAB_SERVICE_MODE && sessionId && peerId ? (cols, rows) => { void resizeServiceTerminal(sessionId, cols, rows, peerId); } : undefined,
        });
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
  const filters = useGrip(SESSION_FILTERS) ?? [];
  const filtersTap = useGrip(SESSION_FILTERS_TAP);
  const toggleFilter = (mod: SessionFilterMod) =>
    filtersTap?.set(filters.includes(mod) ? filters.filter((m) => m !== mod) : [...filters, mod]);
  const showHidden = filters.includes('hidden');
  const draft = useGrip(SESSION_DRAFT) ?? '';
  const draftTap = useGrip(SESSION_DRAFT_TAP);
  const runRepos = useGrip(RUN_REPOS) ?? [''];
  const runReposTap = useGrip(RUN_REPOS_TAP);
  const dialogOpen = useGrip(RUN_DIALOG_OPEN) ?? false;
  const dialogTap = useGrip(RUN_DIALOG_OPEN_TAP);
  const purgeDays = useGrip(PURGE_DAYS) ?? 7;
  const purgeDaysTap = useGrip(PURGE_DAYS_TAP);
  const output = useGrip(SESSION_OUTPUT) ?? '';
  const diag = useGrip(SESSION_DIAGNOSTICS) ?? { kind: 'none', failed: 0, passed: 0, failures: [] };
  const peers = useGrip(PEERS) ?? [];
  const targetPeer = useGrip(SELECTED_PEER_ID) ?? '';
  const peerTap = useGrip(SELECTED_PEER_ID_TAP);
  const theme = useGrip(THEME) ?? 'dark';
  const workspaceRepos = useGrip(WORKSPACE_REPOS) ?? [];

  const nameOf = (id: string) => peers.find((p) => p.id === id)?.name ?? id;
  const availableRepos = workspaceRepos;

  const hiddenCount = sessions.filter((s) => s.hidden).length;
  const wantErrors = filters.includes('errors');
  const wantRunning = filters.includes('running');
  const q = search.trim().toLowerCase();
  const visible = sessions.filter((s) => {
    if (s.hidden && !showHidden) return false; // hidden excluded unless the Hidden modifier is on
    if (wantErrors || wantRunning) {
      const st = sessionStatus(s);
      const match = (wantErrors && st === 'error') || (wantRunning && st === 'running');
      if (!match) return false;
    }
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
    const repos = runRepos.length ? runRepos : [''];
    const { errors } = validateCommand(cmd, runRepos.length);
    if (errors.length) return;
    if (LAB_SERVICE_MODE) {
      void runServiceCommand(cmd.split(/\s+/), repos, targetPeer).then((sessionId) => {
        selectedTap?.set(sessionId);
        selectedTargetTap?.set(repos[0] ?? '');
        draftTap?.set('');
        dialogTap?.set(false);
      });
      return;
    }
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
    dialogTap?.set(false);
  };

  const openTerminal = () => {
    if (LAB_SERVICE_MODE) {
      void openServiceTerminal('', targetPeer).then((sessionId) => {
        selectedTap?.set(sessionId);
        selectedTargetTap?.set('');
      });
      return;
    }
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

  // Re-run a session's exact command against the same set of repos.
  const runAgain = (s: CommandSession) => {
    const cmd = s.argv.join(' ');
    if (LAB_SERVICE_MODE) {
      void runServiceCommand(s.argv, s.targets.map((t) => t.repoPath), s.peerId).then((sessionId) => {
        selectedTap?.set(sessionId);
        selectedTargetTap?.set(s.targets[0]?.repoPath ?? '');
      });
      return;
    }
    const ts = Date.now();
    const targets: RepoRun[] = s.targets.map((t) => ({
      repoPath: t.repoPath,
      exitCode: 0,
      durationMs: 0,
      output: `$ ${cmd}\n\u001b[2m(mock) re-ran in ${repoLabel(t.repoPath)} on ${nameOf(s.peerId)}\u001b[0m\n`,
    }));
    const ns: CommandSession = { id: `sess-${ts}`, peerId: s.peerId, argv: s.argv, startedAt: ts, targets };
    sessionsTap?.set([ns, ...sessions]);
    selectedTap?.set(ns.id);
    selectedTargetTap?.set(targets[0].repoPath);
  };

  // Open the run dialog pre-filled from a session (edit command/repos/collaborator).
  const editSession = (s: CommandSession) => {
    draftTap?.set(s.argv.join(' '));
    runReposTap?.set(s.targets.map((t) => t.repoPath));
    peerTap?.set(s.peerId);
    dialogTap?.set(true);
  };

  const setHidden = (id: string, hidden: boolean) => {
    sessionsTap?.set(sessions.map((s) => (s.id === id ? { ...s, hidden } : s)));
    // When hiding the selected session (and hidden are not shown), move selection on.
    if (hidden && selected === id && !showHidden) {
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
        <div className="filter-mods">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              className={`filter-mod${filters.includes(f.id) ? ' active' : ''}`}
              onClick={() => toggleFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <span className="spacer" />
        <button className="primary" onClick={() => dialogTap?.set(true)}>Run a command…</button>
        <button className="ghost" onClick={openTerminal}>▶ Terminal</button>
      </div>

      {dialogOpen && (() => {
        const { errors, warnings, argv } = validateCommand(draft, runRepos.length);
        const allSelected = availableRepos.length > 0 && availableRepos.every((r) => runRepos.includes(r.path));
        return (
          <div className="modal-backdrop" onClick={() => dialogTap?.set(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-head">
                <strong>Run a command</strong>
                <button className="ghost" onClick={() => dialogTap?.set(false)} title="Close">×</button>
              </div>
              <div className="modal-body modal-cols">
                <div className="dialog-left">
                  <div className="field"><PeerSelect /></div>
                  <div className="field repos-field">
                    <div className="repo-picker-head">
                      <span className="field-label">Repos</span>
                      <span className="spacer" />
                      <span className="muted">{runRepos.length}/{availableRepos.length}</span>
                      <button
                        className="ghost"
                        onClick={() => runReposTap?.set(allSelected ? [] : availableRepos.map((r) => r.path))}
                      >
                        {allSelected ? 'Clear' : 'All'}
                      </button>
                    </div>
                    <div className="repo-picker">
                      {availableRepos.map((r) => {
                        const checked = runRepos.includes(r.path);
                        return (
                          <label key={r.path || 'root'} className={`repo-pick-row${checked ? ' checked' : ''}`}>
                            <input type="checkbox" checked={checked} onChange={() => toggleRepo(r.path)} />
                            <span className="repo-pick-name">{r.name}</span>
                            <span className="repo-pick-path">{r.path || 'root'}</span>
                          </label>
                        );
                      })}
                      {availableRepos.length === 0 && <div className="muted repo-pick-empty">No repos for this collaborator.</div>}
                    </div>
                  </div>
                </div>
                <div className="dialog-right">
                  <div className="field command-field">
                    <span className="field-label">Command</span>
                    <textarea
                      className="command-area"
                      placeholder="uv run pytest -q"
                      value={draft}
                      onChange={(e) => draftTap?.set(e.target.value)}
                    />
                  </div>
                  {argv.length > 0 && (
                    <div className="cmd-preview">program: <code>{argv[0]}</code> · {argv.length} token{argv.length === 1 ? '' : 's'} · {runRepos.length} repo{runRepos.length === 1 ? '' : 's'}</div>
                  )}
                  {errors.map((e, i) => <div key={i} className="cmd-error">✗ {e}</div>)}
                  {warnings.map((w, i) => <div key={i} className="cmd-warn">⚠ {w}</div>)}
                </div>
              </div>
              <div className="modal-foot">
                <button className="ghost" onClick={() => dialogTap?.set(false)}>Cancel</button>
                <button className="primary" disabled={errors.length > 0} onClick={runCommand}>Run</button>
              </div>
            </div>
          </div>
        );
      })()}

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
                    <Avatar peer={peers.find((p) => p.id === s.peerId)} size={13} /> {nameOf(s.peerId)} · {fmtTime(s.startedAt)}
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
                <div className="session-meta"><Avatar peer={peers.find((p) => p.id === current.peerId)} size={16} /> {nameOf(current.peerId)} · {fmtTime(current.startedAt)}</div>
                <span className="spacer" />
                {!current.interactive && (
                  <>
                    <button className="ghost" onClick={() => runAgain(current)} title="Run the same command again on the same repos">↻ Run again</button>
                    <button className="ghost" onClick={() => editSession(current)} title="Edit command / repos / collaborator and run">✎ Edit</button>
                  </>
                )}
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
                termKey={`${current.id}::${activeTarget.repoPath}::${output.length}`}
                content={output}
                interactive={!!current.interactive}
                dark={theme === 'dark'}
                sessionId={current.interactive ? current.id : undefined}
                peerId={current.peerId}
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

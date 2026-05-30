import { type ReactNode } from 'react';
import { useGrip } from '@owebeeone/grip-react';
import { Highlighted } from '../highlight';
import {
  PEERS,
  CHAT_MESSAGES, CHAT_MESSAGES_TAP,
  CHAT_DRAFT, CHAT_DRAFT_TAP,
  CHAT_PENDING, CHAT_PENDING_TAP,
  CHAT_COMPOSER_H, CHAT_COMPOSER_H_TAP,
  CHAT_COMPOSER_DRAG, CHAT_COMPOSER_DRAG_TAP,
  CURRENT_VIEW_TAP, SELECTED_FILE_TAP, SELECTED_PEER_ID_TAP,
  SELECTED_SESSION_TAP, SELECTED_TARGET_TAP,
  DIFF_LEFT_TAP, DIFF_RIGHT_TAP, FOCUS_LINE_TAP,
  WORKSPACE_REPOS, WORKSPACE_TREE, SESSIONS,
} from '../grips';
import { LAB_SERVICE_MODE } from '../dataMode';
import { postServiceChatMessage } from '../serviceClient/chat';
import type { ChatLink, ChatMessage, CommandSession, RepoStatus, WorkspaceTreeEntry } from '../types';
import { parseStateUrl } from '../stateUrl';
import { useEditor } from '../useEditor';
import Avatar from './Avatar';

const LINK_ICON: Record<string, string> = {
  file: '📄', repo: '📁', peer: '👤', session: '⌘', state: '📍',
};

// Stable ref callback: when the last message element mounts (i.e. a new message
// was appended), scroll it into view. Stable identity so it only fires when the
// last element actually changes — no effects/refs.
function scrollLastIntoView(el: HTMLDivElement | null) {
  if (el) el.scrollIntoView({ block: 'end', behavior: 'smooth' });
}

// Render message text, turning ```fenced``` blocks into highlighted code. Plain
// text keeps its newlines (the composer allows Shift+Enter for multi-line).
function MessageBody({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  const re = /```[^\n]*\n?([\s\S]*?)```/g;
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(<span key={key++}>{text.slice(last, m.index)}</span>);
    parts.push(<Highlighted key={key++} code={m[1]} />);
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(<span key={key++}>{text.slice(last)}</span>);
  return <>{parts}</>;
}

function usePalette(): ChatLink[] {
  const peers = useGrip(PEERS) ?? [];
  const tree = (useGrip(WORKSPACE_TREE) ?? []) as WorkspaceTreeEntry[];
  const repos = (useGrip(WORKSPACE_REPOS) ?? []) as RepoStatus[];
  const sessions = (useGrip(SESSIONS) ?? []) as CommandSession[];
  const files: ChatLink[] = tree.filter((entry) => entry.kind === 'file').slice(0, 12).map((f) => ({
    kind: 'file', label: `${f.repoPath}/${f.path}`, target: `${f.repoPath}::${f.path}`,
  }));
  const repoLinks: ChatLink[] = repos.map((r) => ({
    kind: 'repo', label: r.name, target: `repo::${r.path}`,
  }));
  const people: ChatLink[] = peers.filter((p) => !p.isSelf).map((p) => ({
    kind: 'peer', label: p.name, target: `peer::${p.id}`,
  }));
  const sessionLinks: ChatLink[] = sessions.slice(0, 12).map((s) => ({
    kind: 'session', label: s.argv.slice(0, 3).join(' '), target: `session::${s.id}`,
  }));
  return [...files, ...repoLinks, ...people, ...sessionLinks];
}

export default function ChatView({ embedded = false }: { embedded?: boolean }) {
  const peers = useGrip(PEERS) ?? [];
  const sessions = (useGrip(SESSIONS) ?? []) as CommandSession[];
  const messages = useGrip(CHAT_MESSAGES) ?? [];
  const messagesTap = useGrip(CHAT_MESSAGES_TAP);
  const draft = useGrip(CHAT_DRAFT) ?? '';
  const draftTap = useGrip(CHAT_DRAFT_TAP);
  const viewTap = useGrip(CURRENT_VIEW_TAP);
  const fileTap = useGrip(SELECTED_FILE_TAP);
  const peerTap = useGrip(SELECTED_PEER_ID_TAP);
  const sessionTap = useGrip(SELECTED_SESSION_TAP);
  const targetTap = useGrip(SELECTED_TARGET_TAP);
  const diffLeftTap = useGrip(DIFF_LEFT_TAP);
  const diffRightTap = useGrip(DIFF_RIGHT_TAP);
  const focusLineTap = useGrip(FOCUS_LINE_TAP);
  const { openInFiles } = useEditor();

  const palette = usePalette();
  const pending = useGrip(CHAT_PENDING) ?? [];
  const pendingTap = useGrip(CHAT_PENDING_TAP);

  // Composer height + in-progress resize drag, held in grips (no React state).
  const composerH = useGrip(CHAT_COMPOSER_H) ?? 64;
  const composerHTap = useGrip(CHAT_COMPOSER_H_TAP);
  const drag = useGrip(CHAT_COMPOSER_DRAG) ?? null;
  const dragTap = useGrip(CHAT_COMPOSER_DRAG_TAP);

  const selfPeerId = peers.find((p) => p.isSelf)?.id ?? 'me';
  const nameOf = (id: string) => peers.find((p) => p.id === id)?.name ?? id;

  const openLink = (link: ChatLink) => {
    if (link.kind === 'state') {
      // Reproduce UI state from the griplab:// url (grip => value pairs).
      const s = parseStateUrl(link.target);
      if (s.peerId !== undefined) peerTap?.set(s.peerId);
      if (s.diffLeft) diffLeftTap?.set(s.diffLeft);
      if (s.diffRight) diffRightTap?.set(s.diffRight);
      focusLineTap?.set(s.line ?? null);
      if (s.view === 'file' && s.file) {
        openInFiles(s.file);
      } else {
        if (s.file) fileTap?.set(s.file);
        if (s.view) viewTap?.set(s.view);
      }
    } else if (link.kind === 'file') {
      if (link.peerId) peerTap?.set(link.peerId);
      openInFiles(link.target);
    } else if (link.kind === 'peer') { peerTap?.set(link.target.replace('peer::', '')); viewTap?.set('status'); }
    else if (link.kind === 'repo') { viewTap?.set('status'); }
    else if (link.kind === 'session') {
      const sessionId = link.target.replace('session::', '');
      const session = sessions.find((item) => item.id === sessionId);
      if (session) {
        peerTap?.set(session.peerId);
        sessionTap?.set(session.id);
        targetTap?.set(session.targets[0]?.repoPath ?? '');
      }
      viewTap?.set('sessions');
    }
  };

  const send = () => {
    if (!draft.trim() && pending.length === 0) return;
    const ts = Date.now();
    const text = draft.trim();
    if (LAB_SERVICE_MODE) {
      void postServiceChatMessage({ senderId: selfPeerId, text, links: pending })
        .then(() => {
          draftTap?.set('');
          pendingTap?.set([]);
        })
        .catch(() => undefined);
      return;
    }
    const msg: ChatMessage = {
      id: `${ts}-${selfPeerId}-${String(messages.length + 1).padStart(4, '0')}`,
      senderId: selfPeerId,
      ts,
      text,
      links: pending,
    };
    messagesTap?.set([...messages, msg]);
    draftTap?.set('');
    pendingTap?.set([]);
  };

  const startResize = (e: { clientY: number }) => dragTap?.set({ startY: e.clientY, startH: composerH });

  return (
    <section className={`chat-view${embedded ? ' embedded' : ' view'}`}>
      {drag && (
        <div
          className="drag-overlay ns"
          onMouseMove={(e) => composerHTap?.set(Math.max(38, Math.min(400, drag.startH + (drag.startY - e.clientY))))}
          onMouseUp={() => dragTap?.set(null)}
        />
      )}
      {!embedded && (
        <header className="view-head">
          <h2>Chat</h2>
          <p className="muted">Drag a reference into the composer; messages carry live links.</p>
        </header>
      )}

      <div className="chat-log">
        {messages.map((m, i) => (
          <div
            key={m.id}
            ref={i === messages.length - 1 ? scrollLastIntoView : undefined}
            className={`chat-msg${m.senderId === selfPeerId ? ' mine' : ''}`}
          >
            <div className="chat-meta">
              <Avatar peer={peers.find((p) => p.id === m.senderId)} size={18} />
              <strong>{nameOf(m.senderId)}</strong>
              <span className="muted">{new Date(m.ts).toLocaleTimeString()}</span>
            </div>
            {m.text && <div className="chat-text"><MessageBody text={m.text} /></div>}
            {m.links.length > 0 && (
              <div className="chat-links">
                {m.links.map((l, i) => (
                  <button key={i} className={`link-chip ${l.kind}`} onClick={() => openLink(l)}>
                    <span>{LINK_ICON[l.kind]}</span>{l.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="chat-palette">
        <span className="muted">Drag to attach:</span>
        {palette.map((l, i) => (
          <span
            key={i}
            className={`link-chip ${l.kind}`}
            draggable
            onDragStart={(e) => e.dataTransfer.setData('application/json', JSON.stringify(l))}
          >
            <span>{LINK_ICON[l.kind]}</span>{l.label}
          </span>
        ))}
      </div>

      <div className="composer-resize" onMouseDown={startResize} title="Drag to resize the message box">
        <span className="grip-bar" />
      </div>
      <div
        className="chat-composer"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const raw = e.dataTransfer.getData('application/json');
          if (raw) pendingTap?.set([...pending, JSON.parse(raw) as ChatLink]);
        }}
      >
        {pending.length > 0 && (
          <div className="pending-links">
            {pending.map((l, i) => (
              <span key={i} className={`link-chip ${l.kind}`}>
                <span>{LINK_ICON[l.kind]}</span>{l.label}
                <button className="chip-x" onClick={() => pendingTap?.set(pending.filter((_, k) => k !== i))}>×</button>
              </span>
            ))}
          </div>
        )}
        <div className="composer-row">
          <textarea
            value={draft}
            placeholder="Message… (Enter to send, Shift+Enter for newline; drop references above)"
            style={{ height: composerH }}
            onChange={(e) => draftTap?.set(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
            }}
          />
          <button className="primary" onClick={send}>Send</button>
        </div>
      </div>
    </section>
  );
}

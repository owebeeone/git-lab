// Domain types for the grip-lab UI proposal mock.
//
// NOTE: these use TypeScript string-union types as lightweight placeholders for
// the proposal. Concepts with real semantics (OS kind, git file status, link
// kind) will be promoted to proper domain objects in the design phase per
// AGENTS.md; they are kept simple here only to iterate on the UI.

export type ViewId = 'onboarding' | 'status' | 'file' | 'diff' | 'chat' | 'settings' | 'sessions';

export type ThemeId = 'dark' | 'light';

export type OsKind = 'macos' | 'linux' | 'windows';

export type ShellKind = 'bash' | 'zsh' | 'powershell';

// A stock avatar image (emoji on a colored circle — no binary assets).
export interface StockAvatar { id: string; emoji: string; bg: string }
// A peer's chosen avatar: a stock image or a Google-style colored letter.
export type Avatar = { kind: 'stock'; id: string } | { kind: 'letter'; color: string };

// Which collaborator field is being inline-edited.
export interface CollabEdit { peerId: string; field: 'name' | 'sshAddress' | 'location' }

export interface Peer {
  id: string;
  name: string;
  avatar?: Avatar;
  // ssh address used to reach the peer, e.g. "alice@host:22"
  sshAddress: string;
  // remote workspace root (git repo root) on that machine. The same machine can
  // host several worktrees; each (sshAddress + location) pair is a distinct peer.
  location: string;
  // OS + shells are not entered by the user — they are discovered by probing the
  // peer (see "Check"). null/empty means "not checked yet".
  os: OsKind | null;
  shells: ShellKind[];
  online: boolean;
  isSelf: boolean;
}

// Result of probing a peer over its connection.
export interface ProbeResult {
  os: OsKind;
  shells: ShellKind[];
  online: boolean;
}

// Connection-probe state shown while adding a collaborator.
export interface ConnState {
  status: 'idle' | 'connecting' | 'connected';
  os?: OsKind;
  shells?: ShellKind[];
}

// Add-collaborator form state (held in a grip, not React state).
export interface OnboardingForm {
  name: string;
  ssh: string;
  location: string;
  conn: ConnState;
}

// In-progress composer resize drag.
export interface ComposerDrag {
  startY: number;
  startH: number;
}

// In-progress panel resize drag (generic: pointer start + size at drag start).
export interface ResizeDrag {
  start: number;
  startSize: number;
}

// A node as rendered by the workspace graph (produced by the sim engine).
export interface GraphRenderNode {
  id: string;
  repoPath: string;
  name: string;
  branch: string;
  head: string;
  ahead: number;
  behind: number;
  dirty: boolean;
  color: string;
  x: number; y: number; w: number; h: number;
  expanded: boolean;
  changedFiles: ChangedFile[];
}

export type FileChangeKind = 'modified' | 'added' | 'deleted' | 'untracked' | 'renamed';

export interface ChangedFile {
  path: string;
  change: FileChangeKind;
}

export interface RepoStatus {
  // path relative to the workspace root; '' is the root repo itself
  path: string;
  name: string;
  branch: string;
  head: string; // short sha
  ahead: number;
  behind: number;
  dirty: boolean;
  changedFiles: ChangedFile[];
}

export interface DependencyEdge {
  // source depends on target
  source: string;
  target: string;
}

// A monitored file as seen through the (future) delta protocol: a live image of
// contents plus its git status. In the mock this is just static data.
export interface FileImage {
  repoPath: string;
  path: string;
  language: string;
  gitStatus: FileChangeKind | 'clean';
  // contents keyed by ref so the diff viewer can compare any two
  contentsByRef: Partial<Record<FileRef, string>>;
}

export type FileRef = 'working' | 'head';

// An editor column in the Files view: its own open tabs + active file.
export interface EditorGroup {
  id: string;
  open: string[];        // "repoPath::path" keys
  active: string | null; // active tab key
}

export interface DiffEndpoint {
  peerId: string;
  ref: FileRef;
}

export type LinkKind = 'file' | 'repo' | 'peer' | 'session' | 'state';

export interface ChatLink {
  kind: LinkKind;
  label: string;
  // opaque target descriptor the UI knows how to resolve into a view
  target: string;
  // for file links: which collaborator's copy this references (the file is the
  // same; only the peer differs). Undefined => the focused/self peer.
  peerId?: string;
}

export interface ChatMessage {
  // filename-style id: "<ts>-<senderId>-<counter>" (lexicographic ~= chrono)
  id: string;
  senderId: string;
  ts: number;
  text: string;
  links: ChatLink[];
}

// One repo's result within a (possibly multi-repo) command run.
export interface RepoRun {
  repoPath: string;        // '' = root repo
  exitCode: number | null; // null = still running
  durationMs?: number;
  output: string;          // may contain ANSI escape codes
}

export interface CommandSession {
  id: string;
  peerId: string;
  argv: string[];
  startedAt: number;
  interactive?: boolean;   // an open PTY/terminal session
  hidden?: boolean;        // hidden from the default list (not deleted)
  // One entry per repo the command ran on; selectable individually.
  targets: RepoRun[];
}

// Independent filter modifiers (toggles), not mutually exclusive.
export type SessionFilterMod = 'errors' | 'running' | 'hidden';

// Parsed diagnostics extracted from a session's output (e.g. test failures).
export interface SessionDiagnostics {
  kind: 'pytest' | 'none';
  failed: number;
  passed: number;
  failures: string[];
}

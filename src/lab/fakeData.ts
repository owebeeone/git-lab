import type {
  Peer,
  RepoStatus,
  FileImage,
  ChatMessage,
  CommandSession,
} from './types';
import { buildStateUrl } from './stateUrl';

// ---------------------------------------------------------------------------
// Static fake dataset for the UI proposal. Everything here will later be served
// live by the backend via the delta protocol; for now it is hard-coded so the
// UI is clickable and we can iterate on layout/flows.
// ---------------------------------------------------------------------------

export const SELF_ID = 'me';

export const INITIAL_PEERS: Peer[] = [
  {
    id: 'me',
    name: 'You',
    sshAddress: 'you@localhost:3141',
    location: '~/work/grip-pyrolyze-dev',
    os: 'macos',
    shells: ['zsh', 'bash'],
    online: true,
    isSelf: true,
  },
  {
    id: 'alice',
    name: 'Alice',
    sshAddress: 'alice@10.0.0.21:22',
    location: '~/src/grip-pyrolyze-dev',
    os: 'linux',
    shells: ['bash'],
    online: true,
    isSelf: false,
  },
  {
    // Same machine as Alice, different worktree -> a distinct peer.
    id: 'alice-review',
    name: 'Alice (review wt)',
    sshAddress: 'alice@10.0.0.21:22',
    location: '~/review/grip-pyrolyze-dev',
    os: 'linux',
    shells: ['bash'],
    online: true,
    isSelf: false,
  },
  {
    id: 'bob',
    name: 'Bob',
    sshAddress: 'bob@win-box:22',
    location: '%USERPROFILE%/dev/grip-pyrolyze-dev',
    os: 'windows',
    shells: ['powershell'],
    online: false,
    isSelf: false,
  },
];

// Per-peer workspace status. Keyed by peer id. All peers are assumed to have the
// same repo checked out (verified via git); they differ in branch/dirtiness.
export const REPO_STATUS_BY_PEER: Record<string, RepoStatus[]> = {
  me: [
    {
      path: '',
      name: 'grip-pyrolyze-dev',
      branch: 'main',
      head: 'a1b2c3d',
      ahead: 0,
      behind: 0,
      dirty: true,
      changedFiles: [
        { path: 'grip-lab/src/lab/App.tsx', change: 'modified' },
        { path: 'grip-lab/dev-docs/UIProposal.md', change: 'untracked' },
      ],
    },
    {
      path: 'yidl',
      name: 'yidl',
      branch: 'main',
      head: '9f8e7d6',
      ahead: 1,
      behind: 0,
      dirty: false,
      changedFiles: [],
    },
    {
      path: 'astichi',
      name: 'astichi',
      branch: 'perf-refactor',
      head: '4c5d6e7',
      ahead: 0,
      behind: 2,
      dirty: true,
      changedFiles: [{ path: 'src/astichi/engine.py', change: 'modified' }],
    },
  ],
  alice: [
    {
      path: '',
      name: 'grip-pyrolyze-dev',
      branch: 'main',
      head: 'a1b2c3d',
      ahead: 0,
      behind: 0,
      dirty: false,
      changedFiles: [],
    },
    {
      path: 'yidl',
      name: 'yidl',
      branch: 'feature/parser',
      head: '1122334',
      ahead: 3,
      behind: 1,
      dirty: true,
      changedFiles: [
        { path: 'src/yidl/concept_parser.py', change: 'modified' },
        { path: 'tests/generation/test_yidl_lark_parser.py', change: 'modified' },
      ],
    },
    {
      path: 'astichi',
      name: 'astichi',
      branch: 'perf-refactor',
      head: '4c5d6e7',
      ahead: 0,
      behind: 0,
      dirty: false,
      changedFiles: [],
    },
  ],
  'alice-review': [
    {
      path: '',
      name: 'grip-pyrolyze-dev',
      branch: 'review/pr-118',
      head: 'b0a9c8d',
      ahead: 0,
      behind: 0,
      dirty: false,
      changedFiles: [],
    },
    {
      path: 'yidl',
      name: 'yidl',
      branch: 'review/pr-118',
      head: 'b0a9c8d',
      ahead: 0,
      behind: 0,
      dirty: true,
      changedFiles: [{ path: 'src/yidl/cli.py', change: 'modified' }],
    },
    {
      path: 'astichi',
      name: 'astichi',
      branch: 'main',
      head: 'aabbccd',
      ahead: 0,
      behind: 0,
      dirty: false,
      changedFiles: [],
    },
  ],
  bob: [
    {
      path: '',
      name: 'grip-pyrolyze-dev',
      branch: 'main',
      head: '7766554',
      ahead: 0,
      behind: 4,
      dirty: false,
      changedFiles: [],
    },
    {
      path: 'yidl',
      name: 'yidl',
      branch: 'main',
      head: '9f8e7d6',
      ahead: 0,
      behind: 0,
      dirty: false,
      changedFiles: [],
    },
    {
      path: 'astichi',
      name: 'astichi',
      branch: 'main',
      head: 'aabbccd',
      ahead: 0,
      behind: 0,
      dirty: true,
      changedFiles: [{ path: 'README.md', change: 'modified' }],
    },
  ],
};

// A couple of monitored files used by the file + diff viewers.
export const FILE_IMAGES: FileImage[] = [
  {
    repoPath: 'yidl',
    path: 'src/yidl/cli.py',
    language: 'python',
    gitStatus: 'modified',
    contentsByRef: {
      head: `import sys


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: yidl <file>")
        return 1
    # parse the file
    return 0
`,
      working: `import sys


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: yidl <file> [--verbose]")
        return 2
    # parse the file with the new lark grammar
    verbose = "--verbose" in argv
    if verbose:
        print("verbose mode on")
    return 0
`,
    },
  },
  {
    repoPath: 'grip-lab',
    path: 'src/lab/App.tsx',
    language: 'tsx',
    gitStatus: 'modified',
    contentsByRef: {
      head: `export default function App() {
  return <div>hello</div>;
}
`,
      working: `export default function App() {
  const view = useGrip(CURRENT_VIEW);
  return <AppShell view={view} />;
}
`,
    },
  },
];

// Dependency hierarchy between repos (NOT the filesystem layout). In the real
// system this is discovered by an *infrequent* scan (cf. submodule_info_server.py
// reading .gitmodules + a relationship table) and cached/stored — it must not run
// on every render or status poll. Here it is the stored result, keyed by repo
// path; the value lists the repo paths that repo depends on.
export const DEPENDENCIES: Record<string, string[]> = {
  '': ['yidl', 'astichi'],
  yidl: ['astichi'],
  astichi: [],
};

// Build dependency edges (source depends on target) among the present repos.
export function dependencyEdges(repoPaths: string[]): { source: string; target: string }[] {
  const present = new Set(repoPaths);
  const idOf = (p: string) => p || 'root';
  const edges: { source: string; target: string }[] = [];
  for (const p of repoPaths) {
    for (const dep of DEPENDENCIES[p] ?? []) {
      if (present.has(dep)) edges.push({ source: idOf(p), target: idOf(dep) });
    }
  }
  return edges;
}

// Flat file listing for the active workspace's explorer. repoPath '' is the root
// repo; others are submodules. Entries whose key matches a FILE_IMAGES entry get
// real content; the rest render a placeholder in the mock.
export const WORKSPACE_FILES: { repoPath: string; path: string }[] = [
  { repoPath: '', path: 'README.md' },
  { repoPath: '', path: 'project_viewer.py' },
  { repoPath: 'grip-lab', path: 'src/lab/App.tsx' },
  { repoPath: 'grip-lab', path: 'src/lab/grips.ts' },
  { repoPath: 'grip-lab', path: 'dev-docs/UIProposal.md' },
  { repoPath: 'yidl', path: 'src/yidl/cli.py' },
  { repoPath: 'yidl', path: 'src/yidl/concept_parser.py' },
  { repoPath: 'yidl', path: 'tests/generation/test_yidl_lark_parser.py' },
  { repoPath: 'astichi', path: 'src/astichi/engine.py' },
  { repoPath: 'astichi', path: 'README.md' },
];

export const INITIAL_CHAT: ChatMessage[] = [
  {
    id: '1716950000000-alice-0001',
    senderId: 'alice',
    ts: 1716950000000,
    text: 'Can you take a look at the parser changes in yidl?',
    links: [
      { kind: 'file', label: 'yidl/src/yidl/cli.py', target: 'yidl::src/yidl/cli.py' },
    ],
  },
  {
    id: '1716950600000-me-0001',
    senderId: 'me',
    ts: 1716950600000,
    text: 'Looking now. Here is the run I did:',
    links: [{ kind: 'session', label: 'pytest run #42', target: 'session::sess-42' }],
  },
  {
    id: '1716951200000-bob-0001',
    senderId: 'bob',
    ts: 1716951200000,
    text: "My astichi is behind, pulling. Ping @alice when ready.",
    links: [{ kind: 'peer', label: 'Alice', target: 'peer::alice' }],
  },
  {
    id: '1716951800000-alice-0002',
    senderId: 'alice',
    ts: 1716951800000,
    text: 'The early-return guard looks like:\n```python\ndef main(argv: list[str]) -> int:\n    if not argv:\n        return 1\n    return 0\n```\nworks for me now.',
    links: [],
  },
  {
    id: '1716952400000-me-0002',
    senderId: 'me',
    ts: 1716952400000,
    text: 'Look here — this is the exact diff line I mean:',
    links: [
      {
        kind: 'state',
        label: 'yidl/src/yidl/cli.py:L7 (diff)',
        target: buildStateUrl({
          view: 'diff',
          file: 'yidl::src/yidl/cli.py',
          diffLeft: { peerId: 'me', ref: 'head' },
          diffRight: { peerId: 'alice', ref: 'working' },
          line: 7,
        }),
      },
    ],
  },
];

export const COMMAND_SESSIONS: CommandSession[] = [
  {
    id: 'sess-42',
    peerId: 'me',
    cwd: 'yidl',
    argv: ['uv', 'run', 'pytest', '-q', 'tests/generation/test_yidl_lark_parser.py'],
    startedAt: 1716950500000,
    exitCode: 0,
    output: '...\n2963 passed in 12.4s\n',
  },
  {
    id: 'sess-43',
    peerId: 'alice',
    cwd: '',
    argv: ['git', 'status'],
    startedAt: 1716951000000,
    exitCode: 0,
    output: 'On branch feature/parser\nChanges not staged for commit:\n  modified: src/yidl/concept_parser.py\n',
  },
];

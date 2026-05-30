import type {
  DependencyEdge,
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
    avatar: { kind: 'stock', id: 'fox' },
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
    avatar: { kind: 'stock', id: 'panda' },
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
export function dependencyEdges(repoPaths: string[]): DependencyEdge[] {
  const present = new Set(repoPaths);
  const idOf = (p: string) => p || 'root';
  const edges: DependencyEdge[] = [];
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

const ESC = '\u001b';
const green = (s: string) => `${ESC}[32m${s}${ESC}[0m`;
const red = (s: string) => `${ESC}[31m${s}${ESC}[0m`;
const dim = (s: string) => `${ESC}[2m${s}${ESC}[0m`;

export const COMMAND_SESSIONS: CommandSession[] = [
  {
    id: 'sess-42',
    peerId: 'me',
    argv: ['uv', 'run', 'pytest', '-q', 'tests/generation/test_yidl_lark_parser.py'],
    startedAt: 1716950500000,
    targets: [
      {
        repoPath: 'yidl',
        exitCode: 0,
        durationMs: 12400,
        output: `${dim('============================= test session starts =============================')}\ncollected 2963 items\n\n${green('2963 passed')} in 12.40s\n`,
      },
    ],
  },
  {
    // A single command run across multiple repos — one entry, per-repo results.
    id: 'sess-50',
    peerId: 'me',
    argv: ['uv', 'run', 'pytest', '-q'],
    startedAt: 1716952000000,
    targets: [
      {
        repoPath: 'yidl',
        exitCode: 1,
        durationMs: 8700,
        output: `${dim('============================= test session starts =============================')}\ncollected 2965 items\n\ntests/generation/test_yidl_lark_parser.py ......${red('F')}.....${red('F')}\n\n${red('=================================== FAILURES ===================================')}\n${red('____________________ test_parse_named_variadic_kwargs _________________________')}\n\n    assert parsed.kind == "kwargs"\n${red('E   AssertionError: assert \'args\' == \'kwargs\'')}\n\ntests/generation/test_yidl_lark_parser.py:1840: AssertionError\n\n${red('=========================== short test summary info ============================')}\n${red('FAILED tests/generation/test_yidl_lark_parser.py::test_parse_named_variadic_kwargs - AssertionError')}\n${red('FAILED tests/generation/test_yidl_lark_parser.py::test_export_line_roundtrip - KeyError: \'export\'')}\n${red('2 failed')}, 2963 passed in 8.70s\n`,
      },
      {
        repoPath: 'astichi',
        exitCode: 0,
        durationMs: 5200,
        output: `${dim('============================= test session starts =============================')}\ncollected 814 items\n\n${green('814 passed')} in 5.20s\n`,
      },
      {
        repoPath: '',
        exitCode: null,
        output: `${dim('============================= test session starts =============================')}\ncollecting ...`,
      },
    ],
  },
  {
    id: 'sess-43',
    peerId: 'alice',
    argv: ['git', 'status'],
    startedAt: 1716951000000,
    targets: [
      {
        repoPath: '',
        exitCode: 0,
        durationMs: 120,
        output: 'On branch feature/parser\nChanges not staged for commit:\n  (use "git add <file>..." to update what will be committed)\n        modified:   src/yidl/concept_parser.py\n',
      },
    ],
  },
  {
    id: 'sess-61',
    peerId: 'me',
    argv: ['npm', 'run', 'build'],
    startedAt: 1716953000000,
    targets: [
      {
        repoPath: 'grip-lab',
        exitCode: null,
        output: `${dim('> grip-lab@0.0.0 build')}\n${dim('> tsc -b && vite build')}\n\nvite v7.3.3 building client environment for production...\ntransforming...\n`,
      },
    ],
  },
  {
    id: 'sess-70',
    peerId: 'bob',
    argv: ['uv', 'run', 'ruff', 'check', '.'],
    startedAt: 1716953600000,
    targets: [
      {
        repoPath: 'astichi',
        exitCode: 1,
        durationMs: 340,
        output: `${red('src/astichi/engine.py:42:1: F401')} [*] \`os\` imported but unused\n${red('Found 1 error.')}\n`,
      },
    ],
  },
];

# GLTestEnvironDesign

Requirements and design for repeatable integration test environments used by
`grip-lab` services. The first target is a closed localhost SSH environment for
macOS that behaves close enough to a real peer to test probe, bootstrap, remote
git, and command execution flows without depending on external machines.

## Goals

- Provide a realistic SSH peer fixture for service integration tests.
- Run entirely on localhost with generated keys and generated repositories.
- Avoid requiring users to enable system Remote Login.
- Avoid privileged ports, global ssh config, global known-hosts, or permanent
  keys.
- Support real `ssh` command execution against a real `sshd` process.
- Support real `git` commands inside a mock workspace repository.
- Keep the fixture hermetic enough that tests can run repeatedly in any order.
- Make the test environment disposable, auditable, and easy to skip when the
  host cannot support it.

## Non-Goals

- Proving cross-platform parity in v1. macOS is the first tested target.
- Production SSH hardening. This is a local test harness with intentionally
  narrow scope and generated credentials.
- Testing the operating system's SSH service manager.
- Testing password, keyboard-interactive, or agent authentication.
- Testing multi-user login. The v1 fixture logs in as the current test user.
- Running arbitrary unbounded commands without timeout handling.

## First Tested Platform

v1 is first tested on macOS with these tools available:

```text
/usr/sbin/sshd
/usr/bin/ssh
/usr/bin/ssh-keygen
git
```

Tests must skip cleanly when required tools are missing or when `sshd -t` cannot
validate the generated configuration.

The same fixture model should work on Linux with small path/config variants:
`sshd`, `ssh`, `ssh-keygen`, localhost binding, generated keys, and temp git
repositories are the same basic mechanism. Windows OpenSSH Server behavior is
different enough to treat as a separate later design.

## Environment Model

Each test environment owns one temp root:

```text
tmp/
  ssh/
    sshd_config
    sshd.pid
    sshd.log
    known_hosts
    ssh_host_ed25519_key
    ssh_host_ed25519_key.pub
    client_ed25519
    client_ed25519.pub
    authorized_keys
  workspace/
    test-grip-core/
      .git/
      package.json
      .grip-lab/deps.json
    test-grip-react/
      .git/
      package.json
      .grip-lab/deps.json
    test-grip-py/
      .git/
      pyproject.toml
      .grip-lab/deps.json
```

The fixture creates the temp root, starts `sshd`, yields connection details, and
always tears the process and temp files down.

## Fixture API

Python tests should use one fixture object:

```python
@dataclass(frozen=True)
class SshTestPeer:
    host: str
    port: int
    user: str
    identity_file: Path
    known_hosts_file: Path
    workspace_root: Path
    root_repo: Path
    repos: dict[str, Path]
    ssh_command: tuple[str, ...]
```

`ssh_command` contains the base command needed to talk to the fixture:

```text
ssh -o BatchMode=yes -o IdentitiesOnly=yes
    -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile=<fixture-known-hosts>
    -i <fixture-client-key>
    -p <fixture-port>
```

Tests append `<user>@127.0.0.1` and the remote command. Service code under test
should normally receive the equivalent config fields rather than the tuple
directly.

## SSHD Configuration

The fixture writes a private `sshd_config` with:

```text
HostKey <temp host key>
PidFile <temp pid file>
Port <ephemeral port>
ListenAddress 127.0.0.1
AuthorizedKeysFile <temp authorized_keys>
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowUsers <current user>
StrictModes no
UsePAM no
LogLevel ERROR
```

`StrictModes no` is acceptable here because the harness controls the temp tree
and avoids failures caused by platform-specific temp directory ownership rules.

The macOS sftp subsystem path may be included when a test needs sftp:

```text
Subsystem sftp /usr/libexec/sftp-server
```

Most service tests should use normal remote shell commands over SSH, not sftp.

## Keys And Trust

The fixture generates:

- one ed25519 host key for the private `sshd`
- one ed25519 client key for the test
- one `authorized_keys` file containing the generated client public key
- one fixture-local `known_hosts` file

The fixture should pin the generated host key into `known_hosts` before running
service code. Tests should use `StrictHostKeyChecking=yes`; they should not use
`StrictHostKeyChecking=no` except during a low-level harness smoke test that is
specifically proving first-contact behavior.

No key material is committed. No global ssh config is read or modified.

## Data-Driven Mock Workspace

The SSH environment should not hard-code one repo layout. Repo construction is
data-driven so tests can model dependency graphs, language ecosystems, dirty
states, missing manifests, broken installs, and command failures.

Core builder API:

```python
@dataclass(frozen=True)
class RepoSpec:
    name: str
    kind: Literal["react", "pyproject"]
    dependencies: tuple[str, ...] = ()

    def dep(self, *names: str) -> RepoSpec: ...
    def file(self, path: str, content: str) -> RepoSpec: ...
    def dirty(self, path: str, content: str) -> RepoSpec: ...
    def untracked(self, path: str, content: str) -> RepoSpec: ...

@dataclass(frozen=True)
class RepoDefinition:
    repos: tuple[RepoSpec, ...]

    def build(self, workspace_root: Path) -> BuiltWorkspace: ...

CLASSIC = RepoDefinition(
    react_repo("test-grip-core"),
    react_repo("test-grip-react").dep("test-grip-core"),
    react_repo("test-grip-react-demo").dep("test-grip-react"),
    pyproj_repo("test-grip-py"),
)
```

The default workspace should contain real git checkouts:

```text
workspace/
  test-grip-core/
    .git/
    package.json
  test-grip-react/
    .git/
    package.json
  test-grip-react-demo/
    .git/
    package.json
  test-grip-py/
    .git/
    pyproject.toml
```

Each repo baseline:

- `git init`
- local test `user.name` and `user.email`
- initial commit
- project manifest for its ecosystem
- `.grip-lab/deps.json` describing the intended test dependency edges
- optional dirty file changes for status/error tests
- optional untracked files for status/error tests
- optional missing or malformed manifests for scanner error tests

The remote command path should exercise real shell and git behavior:

```text
ssh ... <user>@127.0.0.1 "git -C '<repo>' status --porcelain=v1"
ssh ... <user>@127.0.0.1 "git -C '<repo>' rev-parse --show-toplevel"
```

Paths inside committed fixture definitions must be relative to the test temp
root. Absolute paths are allowed only at runtime in generated temp config and
test process memory.

## Service Config Shape

Tests that drive service code should build config objects equivalent to:

```json
{
  "peerId": "ssh-fixture",
  "displayName": "SSH Fixture",
  "ssh": {
    "host": "127.0.0.1",
    "port": 0,
    "user": "<current user>",
    "identityFile": "<runtime temp key>",
    "knownHostsFile": "<runtime temp known_hosts>",
    "strictHostKeyChecking": true
  },
  "workspace": {
    "workspaceId": "ssh-fixture-main",
    "root": "<runtime temp workspace root>"
  }
}
```

The checked-in documentation and golden files must not contain concrete machine
paths.

## Test Coverage

Harness-level tests:

- skip behavior when `sshd`, `ssh`, or `ssh-keygen` is unavailable
- generated `sshd_config` validates with `sshd -t`
- daemon starts on an ephemeral localhost port
- client key authenticates successfully
- wrong key is rejected
- password auth is unavailable
- host key checking succeeds with fixture `known_hosts`
- host key checking fails with an empty or wrong `known_hosts`
- daemon teardown removes the pid and closes the port

Service integration tests:

- `peer.probe` returns OS, shell, git, and workspace fields through SSH
- remote `git rev-parse` identifies the mock repo root
- remote git status reports clean, dirty, and untracked cases
- data-driven repo definitions build React and Python project manifests
- dependency graph tests can inspect `.grip-lab/deps.json`, `package.json`, and
  `pyproject.toml`
- remote command execution captures stdout, stderr, exit code, and timeout
- command cancellation terminates a long-running remote command
- path validation rejects workspace escapes
- service code never reads global user ssh config during fixture tests

## Timeouts And Cleanup

All SSH commands must have explicit timeouts. Suggested defaults:

- daemon startup: 5 seconds
- simple probe command: 5 seconds
- git command: 10 seconds
- cancellation test command: 10 seconds outer timeout

The fixture teardown must:

- terminate the private `sshd` using the pid file
- wait briefly for process exit
- kill as fallback if needed
- remove the temp root

Tests should print `sshd.log` only on failure.

## Security Boundary

The fixture is safe because it:

- listens only on `127.0.0.1`
- uses an ephemeral port
- allows only the current user
- disables password and keyboard-interactive auth
- accepts only one generated key
- stores host/client keys in a temp directory
- tears the daemon down after each fixture or test session

The fixture is still a real `sshd`. Do not run it with broad `AllowUsers`, a
public listen address, or persistent key material.

## Recommended Implementation Location

```text
services/griplab_service/tests/fixtures/ssh_env.py
services/griplab_service/tests/test_ssh_env.py
services/griplab_service/tests/test_peer_probe_ssh.py
```

Keep the fixture under service tests because it is not part of the product
runtime. Runtime SSH code belongs under:

```text
services/griplab_service/src/griplab_service/ssh_bootstrap.py
```

or a later dedicated SSH module if probe, bootstrap, and remote execution need
separate ownership.

## Roll-Build Placement

Add the SSH fixture before the SSH bootstrap phase if earlier phases need a
stable remote peer target:

- Step 1 or Step 2: harness-only fixture and smoke tests
- Step 8 / Services Phase 10: service `peer.probe` and `peer.bootstrap`
  integration tests use the fixture
- Step 10 / Services Phase 12: cross-peer commands and file access use the
  fixture as the local remote peer

Do not block local workspace/tree/file phases on this fixture unless those
phases explicitly start testing remote behavior.

## Open Questions

- Whether the fixture should be function-scoped for isolation or session-scoped
  for speed.
- Whether remote shell commands should always run through a service-owned
  command builder before any product SSH implementation exists.
- Whether the mock workspace should include real submodules immediately or add
  them when dependency graph tests need them.
- Whether Linux path/config variants should live in the same fixture or a
  separate fixture implementation once Linux is tested.

# GripLab VM Manager Design

## Purpose

`griplab-vm` is the proposed command for managing local test and development machines. Most providers create real VMs, but the Windows story should also support WSL2 because it is the most practical Linux workbench on many Windows machines. The command should make machine use feel close to zero config for day-to-day experiments while still keeping engines pluggable. QEMU should be one backend, not the architecture.

The larger goal is not only "start a VM". The tool should become a small local VM workbench for collaborators, projects, and agents:

- create repeatable VM environments for a project;
- see which VMs exist, what they are for, and who or what is using them;
- share a VM profile with another collaborator without sharing host-specific paths;
- launch one or many agents into managed VMs;
- keep the host secure by limiting privileged setup to initial provider installation and avoiding ongoing elevated access.

## Scope

This design is for a standalone testing tool. It should be useful on its own while we learn what VM workflows actually need.

In scope for the first implementation:

- one `griplab-vm` command;
- local machine provider detection and diagnostics;
- profile-driven machine creation;
- provider-neutral `start`, `stop`, `list`, `info`, `exec`, and `shell`;
- local inventory and logs;
- explicit mount, networking, and credential policy for agent-style testing;
- opt-in provider integration tests.

Out of scope for the first implementation:

- replacing lightweight localhost SSH fixtures used by fast tests;
- automatic registration with any external coordinator;
- a distributed scheduler;
- production-grade autonomous agent orchestration;
- cross-host VM state synchronization.

## Mental Model

A machine manager has two different jobs that are easy to blur together:

- **Provider lifecycle:** create, start, stop, delete, inspect, and exec inside machines using a concrete engine such as Lima, Multipass, OrbStack, or raw QEMU.
- **Tool lifecycle:** decide what machines should exist for a project, what they are named, what role they serve, which workspace they mount, which agents are allowed to run there, and how collaborators discover them locally.

The current prototype mixes these layers. That is fine for an experiment, but it makes every QEMU detail part of the product. The new design keeps one user-facing command and moves engine-specific behavior behind provider adapters.

## Design Principles

- **One CLI, many providers.** Users run `griplab-vm`; provider-specific commands stay behind adapters.
- **Minimal Python dependencies.** Use the Python standard library for the first version. Depend on external provider CLIs rather than SDKs.
- **No provider lock-in.** A VM record stores its provider and provider instance ID. The rest of the tool talks to a common interface.
- **Near zero config.** The default command path should create a usable VM from a profile with no hand-written YAML.
- **Explicit privilege boundary.** Admin access may be needed to install or initialize a provider. Routine `create`, `start`, `stop`, `exec`, `agent`, and `destroy` operations should not call `sudo` on the host.
- **Project-relative sharing.** Files committed to the repo must use paths relative to the owning repo or provider-neutral logical names, not machine-specific absolute paths.
- **Provider-owned networking where possible.** Prefer each provider's SSH, exec, port, and mount mechanisms. Avoid manually rewriting the user's SSH config unless the user asks for it.
- **Testable command generation.** Most behavior should be testable without actually booting VMs.

## Packaging and Layout

The user-facing command should be a standalone script entry point:

```text
griplab-vm
```

Keeping a separate command avoids overloading existing project commands while this is still a VM testing tool. The command can still live in the same Python distribution if that is convenient.

Canonical names:

| Thing | Name |
| --- | --- |
| CLI command | `griplab-vm` |
| Committed project config directory | `vm_manage/` |
| Project config file | `vm_manage/glvm.toml` |
| Local Python implementation package | current package location during prototype work; prefer `vm_manager` when renaming is practical |
| Tests | `tests/vm_manage/` |

The current source tree contains a `vm_manger` directory. That spelling should be treated as legacy while prototyping. New design text, config paths, and tests should use `vm_manage` for project configuration and `vm_manager` for Python package naming when the package is renamed.

## Provider Candidates

### WSL2

WSL2 should be the primary Windows provider for v1. It is not a general-purpose VM manager in the same way as Lima, Multipass, OrbStack, or raw QEMU, but it gives Windows users a reliable Linux execution environment with official lifecycle commands: install, list, import, export, terminate, unregister, and run commands inside a distribution.

Use WSL2 when:

- the host is Windows;
- the goal is a Linux workbench for commands, tests, and agent-style tasks;
- the user wants the least setup after the initial Windows feature enablement;
- the profile can accept WSL's weaker isolation around Windows filesystem access.

Important nuance: WSL2 is best treated as a **machine provider**, not a strict VM isolation provider. It is excellent for low-friction Windows coverage, but mount and credential policy need extra care because Windows files are conveniently reachable from inside WSL. For untrusted tasks on Windows, prefer Multipass when a true VM boundary is required.

### Lima

Lima is a strong default candidate for macOS and Linux users who want Linux VMs with automatic file sharing and port forwarding. It exposes `limactl create`, `start`, `stop`, `delete`, `shell`, `list`, and SSH config discovery. It can run QEMU, VZ, WSL2, and other VM driver modes underneath, which means `griplab-vm` can target Lima without owning every low-level QEMU flag.

Use Lima when:

- the host is macOS or Linux;
- we want provider-managed SSH config and port forwarding;
- we want per-project YAML generation but not a full HashiCorp-style workflow;
- we need good behavior for agent sandboxes with controlled mounts.

Important nuance: Lima defaults may mount host home read-only, and writable mounts are explicit. That is good for agent safety. `griplab-vm` should generate Lima config rather than asking users to hand-edit it.

### Multipass

Multipass is a good Ubuntu-oriented provider with a simple lifecycle: `launch`, `start`, `stop`, `delete`, `exec`, `shell`, `mount`, `transfer`, `info`, and `wait-ready`. It is especially useful when "give me an Ubuntu VM quickly" is the main use case. It is also the Windows fallback when the user wants true VM isolation instead of WSL2.

Use Multipass when:

- Ubuntu is the desired guest OS;
- cross-platform availability matters;
- cloud-init customization is enough;
- a daemon-managed VM service is acceptable.
- Windows has Hyper-V or VirtualBox available and the task needs a real VM boundary.

Important nuance: Multipass has a privileged daemon. After setup, ordinary commands should use the Multipass client, but access to the local daemon is powerful because users with daemon access can manage instances and mounts. `griplab-vm` should document this and avoid widening access automatically.

### OrbStack

OrbStack is attractive on macOS because it provides lightweight Linux machines, built-in SSH, automatic host integration, command execution with `orb`, and cloud-init support. It is not a generic cross-platform provider, but it may be the easiest and fastest provider for Mac users who already run OrbStack.

Use OrbStack when:

- the host is macOS;
- the user already trusts OrbStack for Docker or Linux machines;
- fast startup and many lightweight machines are valuable;
- built-in SSH and easy command execution are more important than raw disk image control.

Important nuance: OrbStack is highly integrated with macOS and creates users with passwordless sudo inside machines by default. That is guest privilege, not host privilege, but agents running inside the machine may still affect mounted host files. Profiles must make mount permissions explicit.

### Raw QEMU

Raw QEMU remains valuable because it is universal, transparent, and powerful. It is also the provider with the most implementation burden: disk image management, SSH readiness, port allocation, cloud-init seed media, process lifecycle, logs, and acceleration flags all become `griplab-vm` responsibilities.

Use raw QEMU when:

- we need exact control over disk images or backing chains;
- Lima, Multipass, and OrbStack are unavailable;
- CI or isolated builder machines need a simple binary-level backend;
- we want a fallback provider for advanced users;
- Raspberry Pi Linux has a 64-bit OS, KVM support, enough memory, and the user has completed one-time setup.

Important nuance: raw QEMU should not be the default user experience until its lifecycle handling, cloud-init, state model, and cleanup behavior are solid.

### Native Host

Some devices are better used directly than as VM hosts. Raspberry Pi Linux is the important case: a Pi can be a valuable managed test machine even when running nested VMs is too slow or unavailable.

Use a native-host provider when:

- the target is a dedicated Raspberry Pi or small Linux box;
- the user wants to run commands, agents, and tests on that host itself;
- virtualization support is missing or not worth the overhead;
- the machine can be reset or reprovisioned by normal package/user management.

Important nuance: native-host is not a VM isolation boundary. It should be opt-in, clearly labeled, and default to conservative workspace and credential handling. It gives us a solid Raspberry Pi story even before QEMU/KVM on ARM is reliable enough for every device.

## Platform Matrix

V1 support should be explicit so users do not expect every provider to behave the same everywhere.

| Host class | Primary story | Secondary story | Notes |
| --- | --- | --- | --- |
| macOS | Lima | OrbStack, then raw QEMU | Lima is the default because it is open, scriptable, and provider-managed; OrbStack is a fast macOS alternative when installed. |
| Windows/WSL | WSL2 provider | Multipass on Hyper-V or VirtualBox | WSL2 gives the lowest-friction Windows path. Multipass is the true-VM option when isolation matters and the host supports it. |
| Raspberry Pi Linux | Native-host provider | raw QEMU/KVM when available | Native-host gives reliable command/agent coverage on Pi hardware. QEMU/KVM is optional for 64-bit Pi setups with enough resources. |
| General Linux workstation | Lima | Multipass, then raw QEMU | Lima keeps behavior close to macOS; Multipass is good for Ubuntu-only workflows. |

This matrix is about `griplab-vm` support, not whether the underlying provider has some platform support. A provider is supported only when detection, diagnostics, create/start/stop/exec, mounts, and tests are reliable enough for this tool.

The test fleet should intentionally cover the three machines available now:

- Mac: Lima primary, OrbStack optional.
- Windows/WSL: WSL2 primary, Multipass optional if Hyper-V or VirtualBox is available.
- Raspberry Pi Linux: native-host primary, QEMU/KVM optional if the KVM device exists and basic boot tests pass.

Each host class should have a no-surprises setup story:

- **Mac:** one-time install of Lima or OrbStack; normal use is unprivileged provider CLI calls.
- **Windows/WSL:** one-time administrator setup may be needed for WSL2 and possibly a reboot; normal use is `wsl` lifecycle and command execution. Multipass may need Hyper-V or VirtualBox setup when a true VM is required.
- **Raspberry Pi Linux:** native-host mode should work with ordinary SSH or local shell access after a normal user is prepared. QEMU/KVM mode may need one-time package installation and group/device access setup; routine use should not call `sudo`.

## Proposed User Experience

Common flow:

```bash
griplab-vm init
griplab-vm doctor
griplab-vm image build --profile dev --name dev-base
griplab-vm create --profile dev --name alice-dev
griplab-vm start alice-dev
griplab-vm exec alice-dev -- uv run pytest
griplab-vm agent launch alice-dev --agent codex --task "inspect failing tests"
griplab-vm list
griplab-vm stop alice-dev
```

Provider selection should be automatic unless requested:

```bash
griplab-vm create --profile dev
griplab-vm create --provider lima --profile dev
griplab-vm create --provider multipass --profile ubuntu-ci
griplab-vm create --provider orbstack --profile mac-fast
griplab-vm create --provider qemu --profile hermetic
```

Provider preference order can be:

1. Project default in `vm_manage/glvm.toml`.
2. User default in local `griplab-vm` state.
3. Auto-detected best provider for the host. On macOS, prefer OrbStack over Lima when both are installed unless the user or project overrides it.
4. QEMU fallback if configured and available.

## CLI Shape

Core commands:

- `init`: create local state, detect provider CLIs, optionally install shell completions, and write a project-local starter config.
- `doctor`: report provider availability, daemon readiness, VM support, disk space, SSH usability, and host privilege risks.
- `providers`: list provider adapters and their status.
- `profiles`: list project VM profiles.
- `aliases`: list resolved OS, network, and provider aliases.
- `image build`: build or refresh a reusable base image/machine for a profile.
- `image list`: list reusable bases known to local state.
- `image delete`: remove a reusable base owned by `griplab-vm`.
- `create`: create a VM from a profile.
- `start`: start a VM.
- `stop`: stop a VM.
- `restart`: stop and start a VM.
- `destroy`: delete a VM and its local inventory record.
- `list`: list known VMs with provider, state, role, project, user, and agent activity.
- `info`: show provider details, mounts, ports, SSH target, and agent status for one VM.
- `exec`: run a command inside a VM through the provider.
- `shell`: open an interactive shell through the provider.
- `ssh-config`: generate an optional SSH include file for tools that need plain SSH targets.
- `sync`: reconcile local inventory with provider reality.
- `repair`: repair local state, SSH material, or provider references where possible.
- `agent launch`: start an agent in a VM with a task, workspace, and policy.
- `agent list`: show active and recent agent runs.
- `agent stop`: stop an agent run.

The first version does not need every command implemented, but the design should leave room for them.

## Project Configuration

Project config should live under `vm_manage/` and be safe to commit:

```toml
# vm_manage/glvm.toml
default_profile = "dev"
default_provider = "auto"

[[profiles]]
name = "dev"
image = "ubuntu-lts"
network = "none"
base = "dev-base"
cpus = 4
memory = "8G"
disk = "40G"
mounts = ["workspace:read-write"]
tools = ["python", "uv", "node"]
roles = ["developer", "agent-runner"]

[[profiles]]
name = "audit"
image = "ubuntu-lts"
network = "none"
base = "audit-base"
cpus = 2
memory = "4G"
disk = "20G"
mounts = ["workspace:read-only"]
tools = ["python", "uv"]
roles = ["reviewer"]
```

Roles are labels for humans and test automation in v1. They do not grant permissions by themselves. Permissions come from explicit mount, network, and credential policy.

Aliases should be project-local and versionable. They let profiles use stable names while the exact resolved value can change over time:

```toml
[os_aliases]
ubuntu-lts = "ubuntu:24.04"
ubuntu-stable = "ubuntu:24.04"
ubuntu-next = "ubuntu:26.04"

[network_aliases]
none = { visibility = "localhost", outbound = false, inbound = false }
full = { visibility = "provider-default", outbound = true, inbound = "localhost" }
subnet-a = { visibility = "subnet-a", outbound = true, inbound = "subnet-a" }

[network_aliases.providers.orbstack.none]
mode = "best-effort-localhost"
outbound = "deny-best-effort"
inbound = "localhost"

[network_aliases.providers.orbstack.full]
mode = "provider-default"
outbound = "allow"
inbound = "localhost"

[network_aliases.providers.orbstack.subnet-a]
mode = "provider-default-with-service-filter"
outbound = "allow"
inbound = "localhost"
allowed_cidrs = ["192.168.64.0/24"]

[network_aliases.providers.lima.none]
mode = "best-effort-localhost"
outbound = "deny-best-effort"
inbound = "localhost"

[network_aliases.providers.lima.full]
mode = "user-v2-default"
outbound = "allow"
inbound = "localhost"

[network_aliases.providers.lima.subnet-a]
mode = "user-v2-default-with-service-filter"
outbound = "allow"
inbound = "localhost"
allowed_cidrs = ["192.168.105.0/24"]

[network_aliases.providers.wsl2.none]
mode = "best-effort-localhost"
outbound = "deny-best-effort"
inbound = "localhost"

[network_aliases.providers.wsl2.full]
mode = "wsl-default-nat"
outbound = "allow"
inbound = "localhost"

[network_aliases.providers.wsl2.subnet-a]
mode = "wsl-default-nat-with-service-filter"
outbound = "allow"
inbound = "localhost"
allowed_cidrs = ["172.16.0.0/12"]

[network_aliases.providers.native_host.none]
mode = "host-configured"
outbound = "host-configured"
inbound = "localhost"

[network_aliases.providers.native_host.full]
mode = "host-configured"
outbound = "host-configured"
inbound = "host-configured"

[network_aliases.providers.native_host.subnet-a]
mode = "host-configured-with-service-filter"
outbound = "host-configured"
inbound = "host-configured"
allowed_cidrs = ["192.168.0.0/16"]

[network_aliases.providers.multipass.none]
mode = "best-effort-localhost"
outbound = "deny-best-effort"
inbound = "localhost"

[network_aliases.providers.multipass.full]
mode = "provider-default-nat"
outbound = "allow"
inbound = "localhost"

[network_aliases.providers.multipass.subnet-a]
mode = "provider-default-nat-with-service-filter"
outbound = "allow"
inbound = "localhost"
allowed_cidrs = ["10.0.0.0/8"]

[network_aliases.providers.qemu.none]
mode = "user-network"
outbound = "deny-best-effort"
inbound = "localhost"

[network_aliases.providers.qemu.full]
mode = "user-network"
outbound = "allow"
inbound = "localhost"

[network_aliases.providers.qemu.subnet-a]
mode = "user-network-with-service-filter"
outbound = "allow"
inbound = "localhost"
allowed_cidrs = ["10.0.2.0/24"]

[[profiles]]
name = "dev"
image = "ubuntu-lts"
network = "none"
base = "dev-base"
```

When a machine is created, the local state records the exact resolved OS image, network policy, and base image used. That means alias definitions can evolve without rewriting every profile or losing reproducibility for existing machines.

Alias definitions can start in `vm_manage/glvm.toml`. If they get large or provider-specific, split them into named files:

```text
vm_manage/aliases/os.toml
vm_manage/aliases/network.toml
vm_manage/aliases/providers/orbstack.toml
vm_manage/aliases/providers/lima.toml
vm_manage/aliases/providers/wsl2.toml
```

The portable alias names should stay stable. Provider-specific files describe how a provider lowers those aliases to its own flags, templates, firewall controls, or best-effort behavior.

Network aliases are a map from a stable name to detailed settings, optionally with provider-specific overrides. V1 should make a best guess for each provider and report when enforcement is best-effort. The initial aliases should be:

- `none`: localhost-only service exposure, no intentional external network access.
- `full`: provider default outbound access and localhost inbound service exposure.
- `subnet-a`: access limited to a named subnet where the provider can enforce it, otherwise a diagnostic that the alias is unsupported or best-effort.

These defaults are intentionally configurable. `allowed_cidrs`, `mode`, `outbound`, and `inbound` may be overridden in project config or provider-specific alias files after testing on real machines. If a provider cannot enforce part of an alias, it should still record the requested policy and print a diagnostic explaining the gap.

Provider-specific tuning should be optional and isolated:

```toml
[providers.lima]
vm_type = "auto"

[providers.multipass]
timeout = "10m"

[providers.orbstack]
enabled = "auto"

[providers.wsl2]
enabled = "auto"

[providers.native_host]
enabled = "auto"

[providers.qemu]
acceleration = "auto"
```

The config should not contain host-specific absolute paths. A mount such as `workspace:read-write` means "the repo workspace as resolved by the local checkout", not a committed host path.

Image names are provider-neutral at the profile layer. Each adapter owns resolution:

| Profile image | Lima | Multipass | OrbStack | QEMU |
| --- | --- | --- | --- | --- |
| `ubuntu:24.04` | generated Lima config using a matching Ubuntu image/template | Multipass image alias or release | OrbStack machine image/distro if available | cloud image URL or local cached image |

If a provider cannot resolve an image, `create` should fail before creating partial state and explain which image names are valid for that provider.

WSL2 and native-host are slightly different:

- WSL2 maps the profile image to an installed or importable distribution. `ubuntu:24.04` should resolve to a matching WSL distro if available, or to an imported root filesystem owned by `griplab-vm`. V1 should allow both dedicated `griplab-vm` imported distros and attaching to an existing user-managed distro.
- Native-host does not create an image. It validates the host OS and architecture against the profile and then records that the current host satisfies the profile. V1 should impose no minimum isolation beyond what the host is configured to provide.

## Local State

Local state is not committed. It should record host-specific facts and provider instance IDs. The default location should be:

```text
user_config_dir/griplab-vm/state.json
user_state_dir/griplab-vm/logs/
```

The exact platform paths should be resolved at runtime from the operating system. They must not be committed into project config.

The state file should include:

```json
{
  "schema_version": 1,
  "project_id": "grip-lab",
  "project_root_hint": "repo-root",
  "bases": {
    "dev-base": {
      "provider": "orbstack",
      "provider_id": "glvm-base-dev",
      "profile": "dev",
      "image_alias": "ubuntu-lts",
      "resolved_image": "ubuntu:24.04",
      "tools": ["python", "uv", "node"],
      "fingerprint": "sha256:profile-and-provider-inputs",
      "stale": false,
      "created_at": "2026-05-30T00:00:00Z"
    }
  },
  "machines": {
    "alice-dev": {
      "provider": "orbstack",
      "provider_id": "glvm-alice-dev",
      "project_id": "grip-lab",
      "profile": "dev",
      "base": "dev-base",
      "image_alias": "ubuntu-lts",
      "resolved_image": "ubuntu:24.04",
      "network_alias": "none",
      "resolved_network": {
        "visibility": "localhost",
        "outbound": false,
        "inbound": false
      },
      "state": "running",
      "owner": "alice",
      "services": {
        "web": {
          "guest_port": 8000,
          "host_port": 49152,
          "visibility": "localhost"
        }
      },
      "last_command_log": "logs/alice-dev/latest.log",
      "created_at": "2026-05-30T00:00:00Z",
      "last_seen_at": "2026-05-30T00:00:00Z"
    }
  }
}
```

`project_id` should be derived from explicit config first, then the repository directory name. `owner` should default to the local username but be overrideable for tests.

State should use atomic writes and file locking. Atomic rename alone protects against torn writes, but it does not protect concurrent read-modify-write cycles; the implementation should use a lock file around state mutations. Corrupt state should fail closed with a repair path, not silently reset and forget existing VMs.

## Provider Interface

Each provider adapter implements the same small interface:

```python
class VMProvider:
    name: str

    def detect(self) -> ProviderStatus: ...
    def doctor(self) -> list[Diagnostic]: ...
    def create(self, spec: MachineSpec) -> ProviderMachine: ...
    def start(self, machine: ProviderMachine) -> None: ...
    def stop(self, machine: ProviderMachine) -> None: ...
    def delete(self, machine: ProviderMachine) -> None: ...
    def list(self) -> list[ProviderMachine]: ...
    def inspect(self, machine: ProviderMachine) -> ProviderMachineInfo: ...
    def exec(self, machine: ProviderMachine, command: list[str], cwd: str | None) -> CommandResult: ...
    def shell(self, machine: ProviderMachine) -> None: ...
    def ssh_target(self, machine: ProviderMachine) -> SSHTarget | None: ...
    def supports(self) -> ProviderCapabilities: ...
```

Capabilities are important because providers differ:

```python
class ProviderCapabilities:
    true_vm_boundary: bool
    cloud_init: bool
    host_mounts: bool
    read_only_mounts: bool
    explicit_port_forwards: bool
    provider_ssh: bool
    snapshots: bool
    clone: bool
    custom_images: bool
    cross_arch: bool
    rootless_daily_ops: bool
```

`griplab-vm` should use capabilities to decide what profile options are valid. For example, a profile requiring QCOW2 backing files should only use QEMU or another provider that exposes compatible reusable images. A profile requiring provider-managed file sharing can use Lima, Multipass, OrbStack, WSL2, or native-host depending on mount policy. A profile requiring a strict VM boundary should reject WSL2 and native-host.

## Provider Mapping

| Operation | Lima | Multipass | OrbStack | WSL2 | Native host | QEMU |
| --- | --- | --- | --- | --- | --- | --- |
| Create | generate config, `limactl create` | `multipass launch` | `orb create` | `wsl --install` or `wsl --import` | register existing host profile | `qemu-img`, cloud-init seed, QEMU boot |
| Start | `limactl start` | `multipass start` | provider command | first `wsl --distribution` command starts it | no-op or health check | spawn QEMU process |
| Stop | `limactl stop` | `multipass stop` | provider command | `wsl --terminate` | no-op or stop managed session | ACPI/poweroff, then terminate |
| Delete | `limactl delete` | `multipass delete` plus purge policy | `orb delete` | `wsl --unregister` for tool-owned distros | unregister local record only | remove disk and state |
| Exec | `limactl shell` | `multipass exec` | `orb -m <name>` | `wsl --distribution <name> -- <cmd>` | SSH or local command runner | SSH command |
| SSH | provider SSH config | provider shell or discovered SSH | built-in SSH host | usually not needed; optional SSH inside distro | SSH if remote, none if local | managed SSH key and forwarded port |
| Mounts | generated Lima YAML | `--mount` or `mount` | provider file sharing | Windows path interop or explicit distro path | existing filesystem or SSH transfer | virtiofs/9p/user-mode fallback |
| Readiness | provider command result | `wait-ready` and `info` | provider command result | `wsl --list --verbose` and command probe | command probe | SSH/cloud-init polling |

The adapter owns the exact CLI syntax. The rest of `griplab-vm` should never format raw provider commands directly.

## Image and Provisioning Model

There are three provisioning layers:

1. **Base image:** the OS image or distro name, such as Ubuntu.
2. **Profile provisioning:** tools and system packages needed for project work.
3. **Run provisioning:** per-agent setup, task checkout, credentials, and temporary files.

For near-zero config, profile provisioning should be expressed once in provider-neutral terms:

```toml
tools = ["python", "uv", "node"]
packages = ["git", "build-essential"]
```

Adapters can lower this to:

- cloud-init user data for Lima, Multipass, OrbStack, and QEMU;
- provider exec commands for post-create repair;
- provider-specific base image or template creation.

Base image building is a v1 feature. It is how `griplab-vm` avoids repeatedly installing the same tools into every VM. The command should support a reusable base per provider/profile:

```bash
griplab-vm image build --profile dev --name dev-base
griplab-vm create --profile dev --base dev-base --name alice-dev
```

Provider implementations may differ:

- QEMU can produce a reusable disk image or QCOW2 backing image.
- Lima can create a prepared template or stopped base instance, then clone or recreate from the same generated config where cloning is unavailable.
- Multipass can use snapshots or a stopped prepared instance when supported by the local driver.
- OrbStack can use machine cloning if available, otherwise a prepared base machine plus replayable provisioning. If OrbStack cannot handle a requested base operation cleanly, `griplab-vm` should fall back to Lima when Lima is installed and the profile is compatible.
- WSL2 can import a prepared root filesystem export.
- Native-host does not build a base image; it records the host as satisfying a profile after validation and optional preparation.

V1 does not need perfect provider parity. It needs a stable `image build/list/delete` interface, exact resolved metadata in local state, and clear diagnostics when a provider cannot produce a reusable base efficiently. If a provider supports snapshots or clones and the user requests that behavior, use it. Otherwise rebuild the base from the resolved profile and provisioning recipe.

Base invalidation should be fingerprint-based. `image build` should compute a digest from:

- the resolved OS image;
- provider name and relevant provider settings;
- CPU, memory, disk, mounts, and network aliases after resolution;
- tool and package lists;
- provisioning scripts or cloud-init content;
- the `griplab-vm` base schema version.

If the current fingerprint differs from the stored base fingerprint, mark the base stale. The recommended default is to rebuild into a new provider-owned base and then update local state after the build succeeds. Existing machines keep using the base they were created from unless the user explicitly recreates them.

## Sharing Model

The tool should distinguish local VM state from shareable project intent.

Shareable:

- VM profiles;
- roles, resource hints, and tool lists;
- agent task templates;
- expected services and logical ports;
- repo-relative workspace roots.

Local only:

- provider choice;
- provider instance ID;
- actual SSH ports and keys;
- host paths resolved from the local checkout;
- running PIDs;
- user identity on the host;
- credentials and tokens.

This split lets collaborators use different providers. One person can use Lima, another can use OrbStack, and CI can use raw QEMU or Multipass while sharing the same `dev` profile.

Export/import can mean three different things, so v1 should be precise:

- **Project definition export/import:** share committed `vm_manage/` profiles and aliases. This is the v1 sharing path.
- **Local inventory export/import:** move local machine records between hosts. This should not be a v1 default because provider IDs, ports, paths, and credentials are host-specific.
- **Provider image export/import:** move actual base images or machine disks. This is useful later for expensive bases, but it should be provider-specific and explicit.

For v1, prefer reproducible setup from shared profiles over moving local state between machines.

## Agent Model

Agents should be launched into VMs through `griplab-vm`, not by giving each agent arbitrary host access.

An agent launch should specify:

- target machine or profile;
- task text;
- workspace mount policy;
- allowed network policy if implemented;
- credential policy;
- lifetime or idle timeout;
- output collection policy.

V1 should support explicit credential injection per run. Credentials should not be baked into base images, committed project config, or long-lived local inventory. The default should still be no credentials unless the command or profile policy explicitly asks for them.

V1 should reuse named project machines by default. Per-agent throwaway machines are useful later, but they add lifecycle cost, cleanup risk, and provider-specific behavior before the basic workflow is proven.

Example:

```bash
griplab-vm agent launch --profile audit --task "review parser changes" --mount workspace:read-only
```

The VM boundary protects the host only if mounts, credentials, and network access are controlled. A read-write workspace mount means the agent can edit the checkout. A read-only workspace mount is safer for inspection and review. A no-mount mode is safest for untrusted tasks but requires explicit file transfer.

## Privilege and Security

The privilege policy should be simple:

- `griplab-vm init` may explain that provider installation needs admin rights.
- `griplab-vm init` may use a preconfigured install script where possible, after explicit user confirmation.
- `griplab-vm init` may call a package manager only through that install path or after an explicit user confirmation.
- Routine VM operations should not call host `sudo`.
- If a provider requires a privileged daemon, `griplab-vm` should report that in `doctor` and avoid changing daemon permissions automatically.
- `griplab-vm` should never blindly overwrite the user's SSH config. Prefer provider SSH commands or a dedicated include block that is opt-in and reversible.
- Host mounts default to read-only for agent-oriented profiles.
- Read-write mounts must be explicit in the profile or command.
- Secrets should be injected per run, not baked into images or committed config.
- Destroy should remove local state and ask the provider to delete the machine; it should not delete unrelated provider machines.

The key nuance: a VM is an isolation boundary, but a writable host mount crosses that boundary. For agents, mount policy matters as much as provider choice.

## SSH Strategy

Use provider-native access first:

- Lima can expose SSH config through `limactl` and supports include-based SSH configuration.
- Multipass supports `exec` and `shell`; direct SSH may be secondary.
- OrbStack exposes a built-in SSH server and command runner.
- QEMU needs `griplab-vm`-managed SSH keys and port forwards.

`griplab-vm ssh-config` can generate an optional SSH include file for tools that need plain SSH. It should write only `griplab-vm`-owned config and instruct the user how to include it, instead of editing arbitrary user SSH config by default.

## Networking

Provider defaults should be used unless a profile declares services:

```toml
[[services]]
name = "web"
guest_port = 8000
host_port = "auto"
visibility = "localhost"
```

`griplab-vm` should track logical services separately from concrete ports. Concrete ports are local state because each collaborator's host may have different conflicts.

For agents, the default network alias should be `none`, meaning localhost-only service exposure and no intentional outbound access beyond what the provider cannot practically block. Broader network modes should be named aliases such as `full` or `subnet-a`, with definitions in project config and optional provider-specific lowering.

## Naming

`griplab-vm` should generate provider-safe names:

```text
glvm-<project-slug>-<profile>-<short-id>
```

The user-facing alias can be shorter:

```text
alice-dev
review-1
agent-42
```

Provider adapters must validate and transform names for provider-specific restrictions. The inventory stores both the local alias and provider ID.

## Error Handling

VM tooling fails in messy ways: missing daemons, stale state, suspended laptops, port conflicts, corrupt disks, half-created machines, and provider CLI changes.

The CLI should prefer:

- dry-run rendering for create commands;
- clear provider diagnostics in `doctor`;
- command logs in local state;
- idempotent create/start/stop where possible;
- reconciliation via `sync`;
- explicit repair commands over silent state resets.

Examples:

```bash
griplab-vm doctor --provider lima
griplab-vm sync
griplab-vm repair alice-dev --recreate-ssh
```

`sync` should have dry-run output before it changes state. It should classify:

- provider machines known to local state;
- provider machines with a `griplab-vm` naming prefix but no local state record;
- local state records whose provider machines no longer exist;
- local state records whose provider machine state differs from the last recorded state.

`repair` should be conservative. It may rebuild local SSH material, refresh provider IDs when a provider can prove identity, or mark stale records as stopped/missing. It should not delete provider machines unless the user explicitly requests destruction.

## Testing Strategy

Most tests should avoid booting real VMs:

- parse project config;
- validate profile defaults;
- render provider commands;
- render cloud-init;
- render optional SSH config;
- exercise local state reads and atomic writes;
- simulate provider CLI output fixtures;
- check diagnostics for missing providers;
- verify privilege policy by asserting routine commands never include `sudo`.

Integration tests can be opt-in and provider-scoped:

```bash
GLVM_INTEGRATION=lima pytest tests/vm_manage
GLVM_INTEGRATION=wsl2 pytest tests/vm_manage
GLVM_INTEGRATION=multipass pytest tests/vm_manage
GLVM_INTEGRATION=native-host pytest tests/vm_manage
GLVM_INTEGRATION=qemu pytest tests/vm_manage
```

Successful end-to-end behavior should be covered by canonical fixtures or integration tests once the harness exists. Bespoke unit tests should focus on command construction, parsing, errors, and diagnostics.

Full provider integration tests should not replace faster local fixtures when a test only needs SSH command behavior. Use real VMs for VM provider lifecycle, mount behavior, provisioning, networking, and agent-style isolation. Use WSL2 and native-host integration tests for their specific lifecycle and command semantics.

## Prototype Migration

The current QEMU-focused prototype is useful as a sketch, but it should not be ported wholesale.

Keep or adapt:

- architecture detection and acceleration flag ideas for the QEMU adapter only;
- port allocation logic, rewritten as a reusable allocator with local state coordination;
- the idea of simple tool recipes, rewritten as provider-neutral provisioning data;
- the command names that still make sense after profile-based creation.

Do not carry forward:

- routine host `sudo` from normal commands;
- global SSH config rewriting by default;
- `StrictHostKeyChecking no` as a blanket policy;
- `ForwardAgent yes` by default;
- ignored provisioning command failures;
- silent reset of corrupt state;
- absolute paths in committed files;
- QEMU-specific disk and process assumptions outside the QEMU adapter.

The old `compile-base` concept should become the v1 `image build` command, but with provider adapters instead of QEMU-specific assumptions. V1 should support reusable bases where the provider can do so cleanly and fall back to replayable provisioning where it cannot.

## First Implementation Slice

1. Keep the existing prototype as reference only.
2. Add a package using the canonical `vm_manager` name when practical, while keeping committed project config under `vm_manage/`.
3. Implement config loading and local state.
4. Implement `provider.detect()` and `doctor` for Lima, WSL2, native-host, Multipass, OrbStack, and QEMU.
5. Implement `list providers`, `profiles`, `aliases`, and dry-run `create`.
6. Implement alias resolution for OS images and network policies, and record exact resolved values in local state.
7. Implement `image build/list/delete` as a provider interface before broad VM creation work.
8. Implement base fingerprints, stale detection, and rebuild behavior.
9. Implement preconfigured provider install scripts for supported hosts.
10. Implement OrbStack create/start/stop/exec/image first on macOS because it is the preferred default when installed.
11. Implement Lima create/start/stop/exec/image as the open macOS/Linux provider and fallback when OrbStack is absent or cannot handle a requested operation.
12. Implement WSL2 create/start/stop/exec/image so Windows has a solid v1 path.
13. Implement native-host register/exec/health so Raspberry Pi Linux has a solid v1 path.
14. Add Multipass create/start/stop/exec/image as the true-VM Windows option and Ubuntu-focused cross-platform option.
15. Add raw QEMU after cloud-init, SSH keys, port allocation, process management, cleanup, and reusable base images are designed as separate tested units.

## Future Extensions

- Snapshot and clone support for providers that expose it.
- Remote VM providers for lab machines or cloud instances.
- A local dashboard showing machines, collaborators, agents, and logs.
- Policy files for what agents may mount, execute, and access.
- Workspace lease management so an agent can claim a VM for a bounded time.
- Provider scorecards from real use: boot time, resource use, mount reliability, SSH reliability, and cleanup behavior.

## Remaining Questions

No blocking design questions remain for v1. Network alias defaults are best guesses and should be adjusted through configuration after testing on the Mac, Windows/WSL, and Raspberry Pi Linux machines.

## References

- Lima documentation describes Linux machines with automatic file sharing, port forwarding, templates, `limactl` lifecycle commands, and SSH config support: <https://lima-vm.io/docs/>
- Multipass documentation describes `launch`, `exec`, `mount`, `wait-ready`, cloud-init, and daemon security considerations: <https://documentation.ubuntu.com/multipass/latest/>
- Multipass installation and driver documentation describes Windows support through Hyper-V or VirtualBox: <https://documentation.ubuntu.com/multipass/stable/how-to-guides/install-multipass/> and <https://documentation.ubuntu.com/multipass/en/latest/explanation/driver/>
- OrbStack documentation describes Linux machines, `orb` commands, cloud-init, built-in SSH, file sharing, and macOS integration: <https://docs.orbstack.dev/machines/>
- Microsoft WSL documentation describes `wsl --install`, `--list`, `--import`, `--export`, `--terminate`, `--unregister`, and command execution: <https://learn.microsoft.com/en-us/windows/wsl/basic-commands>
- Raspberry Pi documentation describes Raspberry Pi OS and 64-bit Raspberry Pi OS support on newer devices: <https://www.raspberrypi.com/documentation/> and <https://www.raspberrypi.com/news/raspberry-pi-os-64-bit/>

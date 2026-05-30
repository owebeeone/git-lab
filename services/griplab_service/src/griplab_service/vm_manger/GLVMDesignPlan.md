# GLVM Build Plan

## Purpose

This plan turns `GLVMDesign.md` into an implementation sequence for the standalone `griplab-vm` testing tool. The goal is to build a useful v1 without pretending all providers are equal on day one.

The plan assumes:

- `griplab-vm` is the user-facing command.
- Project config lives under `vm_manage/`.
- Local state and logs are uncommitted user state.
- OrbStack is preferred on macOS when installed.
- Lima is the macOS/Linux fallback and open provider.
- WSL2 is the primary Windows story.
- Native-host is the primary Raspberry Pi Linux story.
- Multipass is the true-VM Windows option.
- QEMU is advanced/fallback until its lifecycle is solid.

## Milestones

### M0: Skeleton and Tests

Deliverables:

- Python package skeleton for `vm_manager` when practical.
- `griplab-vm` entry point.
- Basic CLI parser with `--help`.
- Test layout under `tests/vm_manage/`.
- Fixture helpers for command rendering and fake provider output.

Acceptance:

- `griplab-vm --help` works.
- Unit tests run without requiring any VM provider.
- No routine command path shells out to `sudo`.

### M1: Config, Aliases, and Local State

Deliverables:

- Load `vm_manage/glvm.toml`.
- Resolve OS aliases and network aliases.
- Support optional provider-specific alias files.
- Implement local state with atomic writes and lock file.
- Add base and machine schema records.
- Add command logs under local user state.

Acceptance:

- Config fixtures parse and validate.
- Alias resolution records exact resolved values.
- Corrupt state fails closed with an actionable error.
- Concurrent state write tests do not lose data.

### M2: Provider Interface and Doctor

Deliverables:

- Common provider interface.
- Provider capability model.
- `providers` command.
- `doctor` command.
- Detection for OrbStack, Lima, WSL2, native-host, Multipass, and QEMU.
- Preconfigured install script hooks where available.

Acceptance:

- Provider detection works from mocked PATH/commands.
- `doctor` distinguishes missing, installed, unhealthy, and unsupported.
- Install scripts are never run without explicit confirmation.

### M3: Image Build Core

Deliverables:

- `image build`, `image list`, `image delete`.
- Base fingerprint computation.
- Stale base detection.
- Rebuild behavior that creates a new provider-owned base before updating state.
- Replayable provisioning model.

Acceptance:

- Fingerprint changes when image/tool/package/provisioning/provider inputs change.
- Stale bases are reported before use.
- Existing machines are not silently moved to a new base.

### M4: OrbStack Provider

Deliverables:

- OrbStack detect/doctor.
- OrbStack create/start/stop/delete/list/info/exec/shell.
- OrbStack image build/list/delete best effort.
- Fallback to Lima when OrbStack cannot handle a requested compatible operation.

Acceptance:

- Unit tests cover command rendering and output parsing.
- Opt-in integration test can create a base, create a machine, exec a command, stop, and destroy.
- Unsupported clone/snapshot behavior falls back or rebuilds with a clear diagnostic.

### M5: Lima Provider

Deliverables:

- Lima config generation.
- Lima create/start/stop/delete/list/info/exec/shell.
- Lima image build/list/delete best effort.
- Mount and service alias lowering.

Acceptance:

- Generated Lima config uses repo-relative logical mounts resolved at runtime.
- Opt-in integration test covers base, machine, exec, and cleanup.
- Network aliases record best-effort gaps.

### M6: WSL2 Provider

Deliverables:

- WSL2 detect/doctor.
- Support attaching to an existing distro.
- Support dedicated imported distro where a rootfs is available.
- WSL2 start/stop/delete/list/info/exec/shell.
- WSL2 image build via export/import where possible.

Acceptance:

- Existing distro attach path works.
- Tool-owned distro delete refuses to delete non-owned distros.
- Integration test on Windows/WSL can exec and clean up owned state.

### M7: Native-Host Provider

Deliverables:

- Native-host register/list/info/exec/health.
- Local and SSH-backed command runner.
- Profile validation against OS/architecture.
- No imposed isolation beyond configured host behavior.

Acceptance:

- Raspberry Pi Linux can register as a native-host target.
- Commands run and logs are captured.
- Destroy unregisters local state without deleting host files.

### M8: Multipass Provider

Deliverables:

- Multipass detect/doctor.
- Multipass create/start/stop/delete/list/info/exec/shell.
- Multipass image build via snapshot/clone when available or replayed provisioning.
- Windows true-VM path diagnostics.

Acceptance:

- Detects driver availability and daemon health.
- Integration test can run on Windows when Multipass is installed.
- Missing Hyper-V/VirtualBox produces a useful diagnostic.

### M9: QEMU Provider

Deliverables:

- QEMU detect/doctor.
- Cloud-init seed generation.
- SSH key management.
- Port allocation coordinated with local state.
- QEMU create/start/stop/delete/list/info/exec/shell.
- QCOW2 reusable bases.

Acceptance:

- QEMU command generation is fully unit-tested.
- Failed SSH readiness cleans up partial state.
- No global SSH config rewrite.
- Integration test is opt-in and skipped by default.

### M10: Agent Commands

Deliverables:

- `agent launch`, `agent list`, `agent stop`.
- Reuse named project machines by default.
- Explicit credential injection per run.
- Mount and network policy recording.
- Log and exit-code capture.

Acceptance:

- No credentials are injected by default.
- Per-run credentials are not stored in project config or long-lived inventory.
- Agent logs are discoverable through `info` or `agent list`.

## Cross-Cutting Rules

- Never commit host-specific absolute paths.
- Never silently reset corrupt local state.
- Never overwrite user SSH config by default.
- Never enable SSH agent forwarding by default.
- Prefer provider-native lifecycle commands.
- If a provider cannot enforce a requested network policy, record the policy and print a diagnostic.
- Use snapshots/clones when requested and available; otherwise rebuild from the resolved recipe.

## Prioritized Test Matrix

The first four priorities must cover the available Mac, Raspberry Pi Linux, Windows/WSL, and the lowest-friction next provider. Later priorities broaden provider coverage without blocking the first usable v1.

| Priority | Host | Provider | Required | Integration Flag | Required Test |
| --- | --- | --- | --- | --- | --- |
| P0 | macOS | OrbStack | yes | `GLVM_INTEGRATION=orbstack` | detect, doctor, image build, create from base, exec, stop, destroy |
| P1 | Raspberry Pi Linux | native-host | yes | `GLVM_INTEGRATION=native-host` | register, doctor, exec, health, log capture, unregister |
| P2 | Windows/WSL | WSL2 | yes | `GLVM_INTEGRATION=wsl2` | detect, attach existing distro, exec, state cleanup, owned-distro safety checks |
| P3 | macOS/Linux | Lima | yes | `GLVM_INTEGRATION=lima` | detect, image build, create from base, exec, stop, destroy; fallback when OrbStack is unavailable |
| P4 | Windows | Multipass | optional v1 | `GLVM_INTEGRATION=multipass` | detect daemon/driver, image build or replay provisioning, create, exec, stop, destroy |
| P5 | macOS/Linux advanced | QEMU | optional v1 | `GLVM_INTEGRATION=qemu` | command rendering, image build, cloud-init, SSH readiness, exec, cleanup |
| P6 | macOS | OrbStack to Lima fallback | optional v1 | `GLVM_INTEGRATION=orbstack-fallback` | force unsupported OrbStack image/base operation and verify compatible Lima fallback |

Priority notes:

- P0 proves the preferred Mac path.
- P1 proves the Raspberry Pi story without requiring VM isolation.
- P2 proves the Windows story through WSL2.
- P3 is the lowest-hanging provider after those three because Lima is open, scriptable, and useful on both macOS and Linux.
- P4 is important for true VM isolation on Windows but depends on local Hyper-V or VirtualBox setup.
- P5 should stay opt-in until QEMU lifecycle, SSH, and cleanup are hardened.
- P6 is useful once OrbStack support exists, but it should not block the primary flow.

## Defer

- Remote provider dashboard.
- Cross-host state sync.
- Provider image export/import beyond explicit provider commands.
- Per-agent throwaway machines.
- Strong network isolation guarantees where providers do not expose enforcement.

# GripLab VM How-To

This guide explains how to use the standalone `griplab-vm` tool to prepare host machines, create managed machines, build reusable bases, run commands inside those machines, and clean up.

The implementation is intentionally a single Python source file:

```text
services/griplab_service/src/griplab_service/vm_manger/griplab_vm.py
```

You can run it through the installed script entry point:

```bash
griplab-vm --help
```

Or directly from the repo:

```bash
PYTHONPATH=services/griplab_service/src python -m griplab_service.vm_manger.griplab_vm --help
```

## Concepts

`griplab-vm` tracks two kinds of local records:

- **bases:** reusable prepared machines/images, created with `image build`.
- **machines:** named work machines, created with `create`.

The project config is committed under:

```text
vm_manage/glvm.toml
```

Local state is not committed. For examples, this guide uses:

```bash
STATE=state/glvm-state.json
```

Use a real local state path when you run the tool.

## Minimal Project Config

Create `vm_manage/glvm.toml`:

```toml
default_profile = "dev"
default_provider = "orbstack"

[os_aliases]
ubuntu-lts = "ubuntu:24.04"

[network_aliases]
none = { visibility = "localhost", outbound = false, inbound = false }
full = { visibility = "provider-default", outbound = true, inbound = "localhost" }

[[profiles]]
name = "dev"
image = "ubuntu-lts"
network = "none"
base = "dev-base"
tools = ["python", "uv"]
```

Aliases let you change `ubuntu-lts` later without rewriting every profile. Existing bases and machines record the exact resolved image they used.

## Inspect the Host

Show available providers:

```bash
griplab-vm providers
```

Show provider diagnostics:

```bash
griplab-vm doctor
```

Show config aliases:

```bash
griplab-vm aliases
```

## Install and Setup Tools

`install-tool` is matrix-based. It prints the install plan by default and only runs it with `--execute`.

Dry-run QEMU install:

```bash
griplab-vm install-tool qemu
```

Run QEMU install:

```bash
griplab-vm install-tool qemu --execute
```

`setup` is a higher-level target wrapper over the same matrix.

Dry-run Raspberry Pi setup:

```bash
griplab-vm setup rpi
```

Run Raspberry Pi setup:

```bash
griplab-vm setup rpi --execute
```

Run these commands on the Raspberry Pi itself, or in an SSH session that lands on the Pi. The setup command selects concrete install commands from the current host platform.

On Raspberry Pi Linux with `apt-get`, the setup currently installs:

```bash
sudo apt-get update
sudo apt-get install -y qemu-system-aarch64 qemu-system-x86 qemu-utils cloud-image-utils
```

Dry-run macOS setup:

```bash
griplab-vm setup macos
```

Dry-run Windows/WSL setup:

```bash
griplab-vm setup windows-wsl
```

Routine VM commands should not use `sudo`. Elevated commands are limited to explicit install/setup flows.

## macOS with OrbStack

OrbStack is the preferred macOS provider when installed.

Build a reusable base:

```bash
griplab-vm --state-file "$STATE" image build --profile dev --name dev-base --provider orbstack
```

Create a machine by cloning that base:

```bash
griplab-vm --state-file "$STATE" create --profile dev --name mac-dev --base dev-base --provider orbstack
```

Run a command inside the machine:

```bash
griplab-vm --state-file "$STATE" exec mac-dev -- uname -a
```

Show machine info:

```bash
griplab-vm --state-file "$STATE" info mac-dev
```

Destroy the machine:

```bash
griplab-vm --state-file "$STATE" destroy mac-dev
```

Delete the base:

```bash
griplab-vm --state-file "$STATE" image delete dev-base
```

What this does under the hood:

```text
orbctl create ubuntu:24.04 glvm-base-dev-base
orbctl clone glvm-base-dev-base glvm-mac-dev
orbctl run --machine glvm-mac-dev uname -a
orbctl delete glvm-mac-dev
orbctl delete glvm-base-dev-base
```

## Raspberry Pi Linux: Native Host

The first Raspberry Pi story is native-host mode. It does not create a VM. It registers the Pi itself as the managed machine and runs commands on that host.

On the Pi, create `vm_manage/glvm.toml`:

```toml
default_profile = "pi"
default_provider = "native-host"

[[profiles]]
name = "pi"
image = "host"
network = "full"
tools = []
```

Register the Pi:

```bash
griplab-vm --state-file "$STATE" create --provider native-host --profile pi --name weftpi
```

Run a command:

```bash
griplab-vm --state-file "$STATE" exec weftpi -- uname -a
```

Show info:

```bash
griplab-vm --state-file "$STATE" info weftpi
```

Unregister the Pi:

```bash
griplab-vm --state-file "$STATE" destroy weftpi
```

Native-host mode imposes no extra isolation beyond how the host is already configured.

## Raspberry Pi Linux: QEMU Preparation

QEMU on Raspberry Pi is an advanced path. Use native-host first, then install QEMU when you want local ARM VM experiments.

Dry-run install:

```bash
griplab-vm setup rpi
```

Run install:

```bash
griplab-vm setup rpi --execute
```

Verify QEMU tools:

```bash
command -v qemu-img
command -v qemu-system-aarch64
```

Also confirm that the host exposes the KVM acceleration device if you expect hardware-accelerated local VMs. The QEMU provider lifecycle is not complete yet. The setup command prepares the host for the future QEMU phase.

## Windows/WSL

The first Windows story is attaching to an existing WSL2 distro. It does not delete or unregister that distro.

Create `vm_manage/glvm.toml`:

```toml
default_profile = "win"
default_provider = "wsl2"

[[profiles]]
name = "win"
image = "ubuntu-lts"
network = "none"
tools = []
```

Attach an existing distro:

```bash
griplab-vm --state-file "$STATE" create --provider wsl2 --profile win --name magenta --distro Ubuntu
```

Run a command:

```bash
griplab-vm --state-file "$STATE" exec magenta -- uname -a
```

Detach local state only:

```bash
griplab-vm --state-file "$STATE" destroy magenta
```

Under the hood, exec uses:

```text
wsl --distribution Ubuntu -- uname -a
```

If SSH lands directly inside WSL, native-host mode may also be useful for testing command execution inside the distro.

## Linux Workstations

Lima and Multipass are planned Linux workstation providers. Current useful modes are:

- `native-host` for direct command execution on the Linux host.
- `setup rpi` or `install-tool qemu` on Debian/Ubuntu-like systems when preparing for QEMU.

Native-host example:

```bash
griplab-vm --state-file "$STATE" create --provider native-host --profile dev --name linux-dev
griplab-vm --state-file "$STATE" exec linux-dev -- uname -a
griplab-vm --state-file "$STATE" destroy linux-dev
```

## Current Provider Status

| Platform | Provider | Status |
| --- | --- | --- |
| macOS | OrbStack | working end-to-end |
| macOS/Linux | native-host | working locally |
| Windows/WSL | WSL2 attach | implemented and unit-tested |
| Raspberry Pi Linux | native-host | ready to run on target |
| Raspberry Pi Linux | QEMU | setup command added; lifecycle pending |
| macOS/Linux | Lima | detection/design only |
| Windows/macOS/Linux | Multipass | detection/design only |

## Safe Cleanup

List local state:

```bash
griplab-vm --state-file "$STATE" list
griplab-vm --state-file "$STATE" image list
```

Destroy a machine:

```bash
griplab-vm --state-file "$STATE" destroy NAME
```

Delete a base:

```bash
griplab-vm --state-file "$STATE" image delete BASE
```

For attached WSL2 distros, `destroy` detaches local state only. It does not run `wsl --unregister`.

## Troubleshooting

If provider detection does not match expectations:

```bash
griplab-vm providers
griplab-vm doctor
```

If state looks wrong, inspect the local state file you passed with `--state-file`. Corrupt state fails closed instead of being silently reset.

If a command requires setup, run the dry-run first:

```bash
griplab-vm setup rpi
griplab-vm install-tool qemu
```

Then run with `--execute` only when the plan looks correct.

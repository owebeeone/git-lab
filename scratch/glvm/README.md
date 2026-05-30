# GLVM Provider Probe Scripts

These scripts collect provider facts from the three target host classes:

- macOS local host
- Windows/WSL host over SSH
- Raspberry Pi Linux host over SSH

They do not create or delete VMs. They only run read-only discovery commands and write logs under `scratch/glvm/outputs/`.

## Setup

1. Copy the environment template:

```bash
cp scratch/glvm/glvm_probe.env.example scratch/glvm/glvm_probe.env
```

2. Edit `scratch/glvm/glvm_probe.env` and set:

```bash
MACOS=LOCAL
WINSSH='user@windows-host'
PISSH='pi@raspberrypi'
WIN_REMOTE_SHELL='wsl bash -s'
PI_REMOTE_SHELL='bash -s'
```

Leave `WINSSH` or `PISSH` empty to skip that host. If SSH lands directly in WSL instead of Windows OpenSSH, set `WIN_REMOTE_SHELL='bash -s'`.

3. Run from the `grip-lab` repo root:

```bash
bash scratch/glvm/run_glvm_probe.sh
```

## Outputs

The collector writes:

```text
scratch/glvm/outputs/<timestamp>/macos/probe.log
scratch/glvm/outputs/<timestamp>/windows-wsl/probe.log
scratch/glvm/outputs/<timestamp>/rpi-linux/probe.log
scratch/glvm/outputs/<timestamp>/summary.txt
```

The remote script is streamed over SSH, so it does not need to write to a remote temporary path.

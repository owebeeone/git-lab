#!/usr/bin/env bash
set -u

section() {
  printf '\n===== %s =====\n' "$1"
}

run() {
  printf '\n$ %s\n' "$*"
  "$@" 2>&1 || printf '[exit %s]\n' "$?"
}

run_shell() {
  printf '\n$ %s\n' "$*"
  sh -lc "$*" 2>&1 || printf '[exit %s]\n' "$?"
}

section "host"
run uname -a
run id
run date -u
run_shell 'printf "SHELL=%s\n" "$SHELL"'
run_shell 'printf "PATH=%s\n" "$PATH"'

section "basic tools"
for tool in sh bash ssh git python python3 systemctl orb orbctl limactl multipass qemu-img wsl; do
  run_shell "command -v $tool"
done

section "macos orbstack"
run_shell 'orbctl version'
run_shell 'orbctl status'
run_shell 'orbctl list --format json'
run_shell 'orbctl create --help'
run_shell 'orbctl clone --help'
run_shell 'orbctl delete --help'
run_shell 'orbctl run --help'
run_shell 'orbctl ssh --help'

section "lima"
run_shell 'limactl --version'
run_shell 'limactl list --json'
run_shell 'limactl create --help'
run_shell 'limactl start --help'
run_shell 'limactl stop --help'
run_shell 'limactl shell --help'

section "multipass"
run_shell 'multipass version'
run_shell 'multipass list --format json'
run_shell 'multipass launch --help'
run_shell 'multipass exec --help'
run_shell 'multipass mount --help'
run_shell 'multipass info --help'

section "wsl"
run_shell 'wsl --status'
run_shell 'wsl --list --verbose'
run_shell 'wsl --help'

section "qemu"
run_shell 'qemu-img --version'
run_shell 'qemu-img --help | head -80'
run_shell 'ls -l /dev/kvm'

section "network"
run_shell 'hostname'
run_shell 'ip addr'
run_shell 'ip route'
run_shell 'ifconfig'
run_shell 'netstat -rn'

section "done"

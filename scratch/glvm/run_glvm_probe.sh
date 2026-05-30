#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GLVM_DIR="$ROOT_DIR/scratch/glvm"
ENV_FILE="$GLVM_DIR/glvm_probe.env"
PROBE_SCRIPT="$GLVM_DIR/probe_host.sh"
OUT_ROOT="$GLVM_DIR/outputs"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$OUT_ROOT/$STAMP"

if [[ ! -f "$ENV_FILE" ]]; then
  printf 'Missing %s\n' "$ENV_FILE" >&2
  printf 'Copy scratch/glvm/glvm_probe.env.example to scratch/glvm/glvm_probe.env and edit it.\n' >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$ENV_FILE"

mkdir -p "$RUN_DIR"

run_local() {
  local name="$1"
  local out_dir="$RUN_DIR/$name"
  mkdir -p "$out_dir"
  printf 'Running local probe: %s\n' "$name"
  bash "$PROBE_SCRIPT" >"$out_dir/probe.log" 2>&1
}

run_remote() {
  local name="$1"
  local target="$2"
  local remote_shell="$3"
  local out_dir="$RUN_DIR/$name"
  mkdir -p "$out_dir"

  if [[ -z "$target" ]]; then
    printf 'Skipping %s: no SSH target configured\n' "$name" | tee "$out_dir/probe.log"
    return 0
  fi

  printf 'Running remote probe: %s (%s)\n' "$name" "$target"
  if ssh ${SSH_OPTS:-} "$target" "$remote_shell" <"$PROBE_SCRIPT" >"$out_dir/probe.log" 2>&1; then
    printf 'ok\n' >"$out_dir/status.txt"
  else
    local exit_code="$?"
    printf 'failed exit=%s\n' "$exit_code" >"$out_dir/status.txt"
    printf 'Remote probe failed: %s (%s), exit=%s\n' "$name" "$target" "$exit_code" >&2
    return 0
  fi
}

if [[ "${MACOS:-}" == "LOCAL" ]]; then
  run_local "macos"
else
  printf 'Skipping macOS: set MACOS=LOCAL to run locally\n'
fi

run_remote "windows-wsl" "${WINSSH:-}" "${WIN_REMOTE_SHELL:-wsl bash -s}"
run_remote "rpi-linux" "${PISSH:-}" "${PI_REMOTE_SHELL:-bash -s}"

{
  printf 'GLVM probe run: %s\n' "$STAMP"
  printf 'Output directory: %s\n' "$RUN_DIR"
  printf '\nFiles:\n'
  find "$RUN_DIR" -type f | sort
} >"$RUN_DIR/summary.txt"

cat "$RUN_DIR/summary.txt"

#!/bin/bash
# Shared helpers for the Project Sniper Mac installer and launchers.
# Sourced, never executed directly.

set -o pipefail

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
APP_DIR="$PKG_ROOT/app"
RUNTIME_DIR="$PKG_ROOT/runtime"
STATE_DIR="$RUNTIME_DIR/state"
LOG_DIR="$RUNTIME_DIR/logs"
ENV_FILE="$RUNTIME_DIR/sniper.env"
PORT="${SNIPER_PORT:-3000}"

# The four executables the render path pins, plus the two provider CLIs, all
# live under runtime/ so nothing global on the buyer's Mac is modified.
CLI_PREFIX="$RUNTIME_DIR/cli"
BROWSER_CACHE="$RUNTIME_DIR/browser"
WHISPER_DIR="$RUNTIME_DIR/whisper"
CLAUDE_CONFIG_DIR_LOCAL="$RUNTIME_DIR/claude-config"
CODEX_HOME_LOCAL="$RUNTIME_DIR/codex-home"

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
fail() { printf 'STOPPED: %s\n' "$*" >&2; exit 1; }

# Log without ever writing an environment value or command output that could
# carry a token: callers pass a message, not a captured stdout.
log_line() {
  mkdir -p "$LOG_DIR"
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG_DIR/install.log"
}

require_macos() {
  [ "$(uname -s)" = "Darwin" ] || fail "Project Sniper runs on macOS only."
  local major
  major="$(sw_vers -productVersion | cut -d. -f1)"
  [ "$major" -ge 14 ] 2>/dev/null || warn \
    "macOS $(sw_vers -productVersion) is below the tested baseline. The only qualified
  baseline is macOS 26 on Apple silicon; anything else is untested."
  [ "$(uname -m)" = "arm64" ] || warn \
    "This Mac is $(uname -m). Only Apple silicon (arm64) is qualified; Intel is untested."
}

# The voice-rnn dialogue-cleanup preset builds an ffmpeg filtergraph that embeds
# this directory's absolute path, so these characters break it (app/scripts/
# producer/audio/audio_enhance.py refuses to run and tells you to move it).
require_safe_install_path() {
  case "$PKG_ROOT" in
    *,*|*\'*|*:*|*\\*)
      fail "The install folder path contains one of  ,  '  :  \\  which breaks the
  audio cleanup filter. Move this folder somewhere without those characters
  (spaces and accents are fine) and run the installer again.
  Current path: $PKG_ROOT" ;;
  esac
}

node_ok() {
  local major
  major="$(node --version 2>/dev/null | sed 's/^v//' | cut -d. -f1)" || return 1
  [ -n "$major" ] && [ "$major" -ge 22 ] 2>/dev/null
}

python_ok() {
  local candidate="$1"
  "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    >/dev/null 2>&1
}

find_python() {
  local candidate
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && python_ok "$(command -v "$candidate")"; then
      command -v "$candidate"; return 0
    fi
  done
  return 1
}

# Every launcher and the doctor read exactly this file, so the app, the review
# links and the diagnostics can never disagree about a resolved path.
load_env() {
  [ -f "$ENV_FILE" ] || fail "Not installed yet. Run install.command first."
  set -a; . "$ENV_FILE"; set +a
}

port_listener() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $1" (pid "$2")"}' | sort -u
}

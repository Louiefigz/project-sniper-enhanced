#!/bin/bash
# Shared helpers for the Project Sniper Mac installer and launchers.
# Sourced, never executed directly.

set -o pipefail

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
APP_DIR="$PKG_ROOT/app"
RUNTIME_DIR="$PKG_ROOT/runtime"
STATE_DIR="$RUNTIME_DIR/state"
RECEIPTS="$STATE_DIR/receipts"
LOG_DIR="$RUNTIME_DIR/logs"
ENV_FILE="$RUNTIME_DIR/sniper.env"
PORT="${SNIPER_PORT:-3000}"

CLI_PREFIX="$RUNTIME_DIR/cli"
CLI_BIN="$CLI_PREFIX/node_modules/.bin"
BROWSER_CACHE="$RUNTIME_DIR/browser"
WHISPER_DIR="$RUNTIME_DIR/whisper"
CLAUDE_CONFIG_DIR_LOCAL="$RUNTIME_DIR/claude-config"
CODEX_HOME_LOCAL="$RUNTIME_DIR/codex-home"

# A double-clicked .command starts with a minimal PATH that omits Homebrew.
# Add the standard Homebrew locations so Finder and Terminal launches agree.
case ":$PATH:" in *":/opt/homebrew/bin:"*) ;; *) PATH="/opt/homebrew/bin:$PATH" ;; esac
case ":$PATH:" in *":/usr/local/bin:"*) ;; *) PATH="$PATH:/usr/local/bin" ;; esac
export PATH

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
fail() { printf 'STOPPED: %s\n' "$*" >&2; log_line "stopped: ${1%%$'\n'*}"; exit 1; }

log_line() {
  mkdir -p "$LOG_DIR"
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG_DIR/install.log"
}

sha() { shasum -a 256 "$1" | awk '{print $1}'; }

# A completion receipt records exactly what a finished step was built from.
# A step is skipped only when its receipt matches the current inputs; the mere
# existence of node_modules, a venv or a download is never treated as done.
receipt_ok() {  # name expected-value
  [ -f "$RECEIPTS/$1" ] && [ "$(cat "$RECEIPTS/$1")" = "$2" ]
}
write_receipt() {  # name value
  mkdir -p "$RECEIPTS"; printf '%s' "$2" > "$RECEIPTS/$1.tmp" && mv "$RECEIPTS/$1.tmp" "$RECEIPTS/$1"
}
clear_receipt() { rm -f "$RECEIPTS/$1"; }

require_macos() {
  [ "$(uname -s)" = "Darwin" ] || fail "Project Sniper runs on macOS only."
  [ "$(uname -m)" = "arm64" ] || warn "This Mac is $(uname -m). Only Apple silicon has been
  tested; this Mac is outside the tested set."
}

# The voice-rnn dialogue-cleanup preset embeds this folder's path in an ffmpeg
# filtergraph; these characters make the product refuse to run it
# (app/scripts/producer/audio/audio_enhance.py). This check reports that limit
# before install; it does not repair the underlying path handling.
require_safe_install_path() {
  case "$PKG_ROOT" in
    *,*|*\'*|*:*|*\\*)
      fail "The folder path contains one of  ,  '  :  \\  which the audio cleanup
  filter cannot handle. Move this folder somewhere without those characters
  (spaces and accents are fine) and run the installer again.
  Current path: $PKG_ROOT" ;;
  esac
}

node_major() { node --version 2>/dev/null | sed 's/^v//' | cut -d. -f1; }

python_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1
}

find_python() {
  local candidate
  for candidate in python3.14 python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && python_ok "$(command -v "$candidate")"; then
      command -v "$candidate"; return 0
    fi
  done
  return 1
}

# Every filter and encoder the render chain actually uses, checked on the
# ffmpeg this install will run — not assumed from a version string.
FFMPEG_FILTERS="rubberband zscale subtitles ass drawtext arnndn loudnorm ebur128 afftdn acompressor alimiter sidechaincompress aresample amix overlay crop"
ffmpeg_missing_features() {
  local have enc
  have="$("$1" -hide_banner -filters 2>/dev/null | awk '{print $2}')"
  enc="$("$1" -hide_banner -encoders 2>/dev/null | awk '{print $2}')"
  for f in $FFMPEG_FILTERS; do printf '%s\n' "$have" | grep -qx "$f" || printf '%s ' "$f"; done
  for e in libx264 aac; do printf '%s\n' "$enc" | grep -qx "$e" || printf '%s ' "$e"; done
}

# Read one KEY from the env file without executing anything else in it.
env_value() {
  [ -f "$ENV_FILE" ] || return 1
  sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p" "$ENV_FILE" | tail -1
}

load_env() {
  [ -f "$ENV_FILE" ] || fail "Not installed yet. Run install/install.command first."
  set -a; . "$ENV_FILE"
  [ -f "$RUNTIME_DIR/sniper.local.env" ] && . "$RUNTIME_DIR/sniper.local.env"
  set +a
}

port_listener_pids() {
  lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | sort -u
}

# A stored PID is only ours if that process is still this package's supervisor.
# PIDs are reused; signalling one blindly could stop an unrelated program.
pid_is_our_supervisor() {
  local pid="$1" cmd
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || return 1
  cmd="$(ps -o command= -p "$pid" 2>/dev/null)"
  case "$cmd" in *"$APP_DIR/scripts/infra/next_supervisor.mjs"*|*"scripts/infra/next_supervisor.mjs"*)
    [ "$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')" = "$APP_DIR" ] ;;
    *) return 1 ;;
  esac
}

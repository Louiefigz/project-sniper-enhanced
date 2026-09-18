#!/bin/bash
# Shared helpers for the Project Sniper Mac installer and launchers.
# Sourced, never executed directly. Its parts: lib/settings.sh (the settings
# file), lib/tools.sh (Node, Python and the other executables Sniper uses) and
# lib/processes.sh (which processes belong to this install).

set -o pipefail

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
APP_DIR="$PKG_ROOT/app"
RUNTIME_DIR="$PKG_ROOT/runtime"
STATE_DIR="$RUNTIME_DIR/state"
RECEIPTS="$STATE_DIR/receipts"
LOG_DIR="$RUNTIME_DIR/logs"
ENV_FILE="$RUNTIME_DIR/sniper.env"
LOCAL_ENV="$RUNTIME_DIR/sniper.local.env"
RELEASE_JSON="$PKG_ROOT/RELEASE.json"
PORT="${SNIPER_PORT:-3000}"
SCRIPT_PATH="$(cd "$(dirname "$0")" 2>/dev/null && pwd -P)/$(basename "$0")"

CLI_PREFIX="$RUNTIME_DIR/cli"
CLI_BIN="$CLI_PREFIX/node_modules/.bin"
RUNTIME_BIN="$RUNTIME_DIR/bin"
BROWSER_CACHE="$RUNTIME_DIR/browser"
WHISPER_DIR="$RUNTIME_DIR/whisper"
CLAUDE_CONFIG_DIR_LOCAL="$RUNTIME_DIR/claude-config"
CODEX_HOME_LOCAL="$RUNTIME_DIR/codex-home"
LOCK_TOOL="$APP_DIR/scripts/infra/sniper_lock.py"
INSTALL_TOOLS="$PKG_ROOT/install/lib/install_tools.py"

# A double-clicked .command can start with a minimal PATH that omits Homebrew.
# Add the standard Homebrew locations AFTER whatever the caller has, so a Node
# from nvm, fnm or volta that Terminal puts first is still the one found.
case ":$PATH:" in *":/opt/homebrew/bin:"*) ;; *) PATH="$PATH:/opt/homebrew/bin" ;; esac
case ":$PATH:" in *":/usr/local/bin:"*) ;; *) PATH="$PATH:/usr/local/bin" ;; esac
export PATH
# The pinned Claude CLI names its Keychain login after CLAUDE_CONFIG_DIR, so
# Sniper's login is separate from yours. This variable would override that
# naming and point Sniper's sign-in and sign-out at your own login; never inherit it.
unset CLAUDE_SECURESTORAGE_CONFIG_DIR
# Sniper runs on subscriptions. A key or cloud-billing switch exported in your
# shell must never be billed by accident. A key you deliberately put in
# runtime/sniper.local.env or app/.env.local is still read (Frame Review, and
# Segmenter/Clipper on the Claude route, which call the paid API).
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_OAUTH_TOKEN OPENAI_API_KEY \
      ANTHROPIC_BASE_URL CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
fail() { printf 'STOPPED: %s\n' "$*" >&2; log_line "stopped: ${1%%$'\n'*}"; exit 1; }

log_line() {
  mkdir -p "$LOG_DIR" 2>/dev/null || return 0
  printf '%s %s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$(basename "$0")" "$*" >> "$LOG_DIR/install.log"
}

sha() { shasum -a 256 "$1" | awk '{print $1}'; }

# A completion receipt records exactly what a finished step was built from.
# A step is skipped only when its receipt matches the current inputs AND its
# output still verifies; the mere existence of a folder is never treated as done.
receipt_ok() {  # name expected-value
  [ -f "$RECEIPTS/$1" ] && [ "$(cat "$RECEIPTS/$1")" = "$2" ]
}
write_receipt() {  # name value
  mkdir -p "$RECEIPTS"; printf '%s' "$2" > "$RECEIPTS/$1.tmp" && mv "$RECEIPTS/$1.tmp" "$RECEIPTS/$1"
}
clear_receipt() { rm -f "$RECEIPTS/$1" "$RECEIPTS/$1.tree.json"; }

require_macos() {
  [ "$(uname -s)" = "Darwin" ] || fail "Project Sniper runs on macOS only."
  [ "$(uname -m)" = "arm64" ] || warn "This Mac is $(uname -m). Only Apple silicon has been
  tested; this Mac is outside the tested set."
}

# The voice-rnn dialogue-cleanup preset embeds this folder's path in an ffmpeg
# filtergraph, where , ' : and \ are syntax; the product refuses to run it from
# such a path (app/scripts/producer/audio/audio_enhance.py). That is the only
# reason a character is refused: settings are stored literally (lib/settings.sh).
require_safe_install_path() {
  case "$PKG_ROOT" in
    *,*|*\'*|*:*|*\\*)
      fail "The folder path contains one of  ,  '  :  \\  which the audio-cleanup filter
  cannot handle. Move this folder somewhere without those characters and run the
  installer again. Current path: $PKG_ROOT" ;;
  esac
}

# The Python that runs Sniper's own helpers: the app's environment once it
# exists, otherwise a Python 3.12+ from this Mac (the lock helper is stdlib only).
sniper_python() {
  if [ -x "$APP_DIR/.venv/bin/python3" ] && python_ok "$APP_DIR/.venv/bin/python3"; then
    printf '%s' "$APP_DIR/.venv/bin/python3"; return 0
  fi
  find_python
}

# One value from RELEASE.json ("components.node_floor" style dotted keys).
release_value() {
  local py
  py="$(sniper_python)" || fail "Python 3.12 or newer is required to read RELEASE.json."
  "$py" -c 'import json,sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
for key in sys.argv[2].split("."):
    value = value[key]
print(" ".join(map(str, value)) if isinstance(value, list) else value)' "$RELEASE_JSON" "$1" \
    || fail "RELEASE.json has no $1; this folder is incomplete."
}

# hold_maintenance MODE LABEL BUSY-MESSAGE [this script's arguments...]
# Re-run this script while holding the install's maintenance lock
# (app/scripts/infra/sniper_lock.py): exclusive for installing, switching
# provider, cleaning and removing; shared for anything that uses the install.
# The lock is held until this script and everything it started have exited.
hold_maintenance() {
  local mode="$1" label="$2" busy="$3" py
  shift 3
  [ "${SNIPER_LOCKED_PID:-}" = "$$" ] && return 0
  py="$(sniper_python)" || fail "Python 3.12 or newer is required (see the manual's install page)."
  [ -f "$LOCK_TOOL" ] || fail "This folder is incomplete: $LOCK_TOOL is missing."
  mkdir -p "$STATE_DIR" || fail "Cannot create $STATE_DIR"
  export SNIPER_LOCKED_PID=$$
  exec "$py" "$LOCK_TOOL" exec --state-dir "$STATE_DIR" --mode "$mode" --label "$label" \
    --busy-message "$busy" -- /bin/bash "$SCRIPT_PATH" "$@"
}

. "$PKG_ROOT/install/lib/settings.sh"
. "$PKG_ROOT/install/lib/tools.sh"
. "$PKG_ROOT/install/lib/processes.sh"

# Load this install's settings: the installer's data file (literally), then your
# own runtime/sniper.local.env (shell syntax, by design). A port given on the
# command line (SNIPER_PORT=3100 install/start.command) wins over both.
# The folder is always taken from where these scripts are, never from the settings
# file: after a move or copy the settings still name the old place, and acting on
# it could stop or delete another install. `load_env --moved-ok` (uninstall only)
# continues with this folder's own paths instead of refusing.
load_env() {
  local caller_port="${SNIPER_PORT:-}" here="$PKG_ROOT" recorded provider brain
  [ -f "$ENV_FILE" ] || fail "Not installed yet. Run install/install.command first."
  settings_load "$ENV_FILE"
  provider="${SNIPER_PROVIDER:-}"; brain="${SNIPER_BRAIN_PROVIDER:-}"
  if [ -f "$LOCAL_ENV" ]; then
    set -a; . "$LOCAL_ENV" || fail "runtime/sniper.local.env has an error (it is read as shell)."; set +a
  fi
  # Guided setup owns this optional connection. Read as literal data, never shell.
  # An empty key records an explicit disconnect and overrides older manual keys.
  if [ -f "$RUNTIME_DIR/deepgram.env" ]; then
    settings_load "$RUNTIME_DIR/deepgram.env" || fail "Reopen install/setup.command to repair the Deepgram connection."
  fi
  recorded="$PKG_ROOT"; PKG_ROOT="$here"; APP_DIR="$here/app"; export PKG_ROOT APP_DIR
  if [ "$recorded" != "$here" ] && [ "${1:-}" != "--moved-ok" ]; then
    fail "This folder was moved or copied after it was installed (installed at:
  $recorded). Run install/install.command once in its new place."
  fi
  [ "${1:-}" = "--moved-ok" ] || check_provider_settings "$provider" "$brain"
  [ -n "$caller_port" ] && SNIPER_PORT="$caller_port"
  PORT="${SNIPER_PORT:-3000}"; export SNIPER_PORT="$PORT"
}

# The Node this install was set up with must still be there and still be new
# enough; a Homebrew upgrade or an nvm uninstall removes it.
require_installed_node() {
  local problem
  problem="$(node_problem "${SNIPER_NODE_PATH:-}" "$(release_value components.node_floor)")"
  [ -z "$problem" ] || fail "The Node this install was set up with cannot be used: $problem.
  Run install/install.command again; it sets up with the Node on your PATH now."
}

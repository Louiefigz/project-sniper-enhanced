#!/bin/bash
# Shared helpers for the Project Sniper macOS installer and launchers.
# Sourced, never executed directly. Its parts: lib/settings.sh (the settings
# file), lib/tools.sh (Node, Python and the other executables Sniper uses) and
# lib/processes.sh (which processes belong to this install).

set -o pipefail

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
APP_DIR="$PKG_ROOT"   # the app is the package folder itself: the folder you open in Codex or Claude Code
RUNTIME_DIR="$PKG_ROOT/runtime"
STATE_DIR="$RUNTIME_DIR/state"
RECEIPTS="$STATE_DIR/receipts"
LOG_DIR="$RUNTIME_DIR/logs"
ENV_FILE="$RUNTIME_DIR/sniper.env"
LOCAL_ENV="$RUNTIME_DIR/sniper.local.env"
KEPT_WORKSPACE="$RUNTIME_DIR/workspace.env"   # which folder the projects are in, kept by uninstall
RELEASE_JSON="$PKG_ROOT/RELEASE.json"
SCRIPT_PATH="$(cd "$(dirname "$0")" 2>/dev/null && pwd -P)/$(basename "$0")"

RUNTIME_BIN="$RUNTIME_DIR/bin"
BROWSER_CACHE="$RUNTIME_DIR/browser"
WHISPER_DIR="$RUNTIME_DIR/whisper"
LOCK_TOOL="$APP_DIR/scripts/infra/sniper_lock.py"
INSTALL_TOOLS="$PKG_ROOT/install/lib/install_tools.py"

# These scripts use macOS's own utilities only. Sniper brings its own Node, Python and media
# tools (lib/runtime_tools.sh), so nothing from Homebrew, nvm or another PATH entry may stand
# in for them — or for tar, stat or awk, whose GNU versions behave differently. The app gets
# its own PATH from the settings (load_env).
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
. "$PKG_ROOT/install/lib/platform.sh" || exit 1
# Settings for your own Python, Node or libraries would steer Sniper's instead (a
# DYLD_LIBRARY_PATH to Homebrew would load Homebrew's libraries into Sniper's ffmpeg;
# NODE_OPTIONS could load code into every Sniper process). They never reach Sniper.
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE NODE_OPTIONS NODE_PATH \
      DYLD_LIBRARY_PATH DYLD_FALLBACK_LIBRARY_PATH DYLD_INSERT_LIBRARIES DYLD_FRAMEWORK_PATH \
      CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL MAMBA_ROOT_PREFIX CONDARC MAMBARC \
      FONTCONFIG_FILE FONTCONFIG_PATH TESSDATA_PREFIX
# (A certificate bundle you set, e.g. for a company proxy, is kept: downloads need it.)
# macOS gives every login session a private temporary folder (TMPDIR). A launcher started with a
# cleared environment has none, so temporary files land under /tmp — and Leptonica (tesseract's
# image reader, Homebrew's and Sniper's alike) rewrites /tmp paths and then cannot find them.
[ -n "${TMPDIR:-}" ] || TMPDIR="$(/usr/bin/getconf DARWIN_USER_TEMP_DIR)"
export TMPDIR
# Sniper's own tools never call a provider: your Codex or Claude Code does the thinking on your
# subscription. A key or cloud-billing switch exported in your shell is not passed to them.
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

# SHA-256 of a file. shasum is a Perl script; openssl is the fallback should Perl be absent.
sha() {
  local out
  out="$(/usr/bin/shasum -a 256 "$1" 2>/dev/null)" || out="$(/usr/bin/openssl dgst -sha256 -r "$1")" || return 1
  printf '%s' "${out%% *}"
}

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

# Sniper's own tools are native to this Mac and name the oldest macOS they run on.
# platform.sh uses sysctl so a Terminal under Rosetta still selects arm64 on Apple silicon.
require_macos() {
  local have need
  [ "$(uname -s)" = "Darwin" ] || fail "Project Sniper runs on macOS only."
  have="$(/usr/bin/sw_vers -productVersion)"; need="$(deps_header min-macos)" || need=12.0
  version_ge "$have" "$need" || fail "This Mac runs macOS $have; Sniper's tools need macOS $need or
  later. Update macOS (Software Update: System Settings > General, or System Preferences on
  macOS 12 and earlier), then run this again."
}

# The voice-rnn dialogue-cleanup preset embeds this folder's path in an ffmpeg
# filtergraph, where , ' : and \ are syntax; the product refuses to run it from
# such a path (scripts/producer/audio/audio_enhance.py). That is the only
# reason a character is refused: settings are stored literally (lib/settings.sh).
require_safe_install_path() {
  case "$PKG_ROOT" in
    *,*|*\'*|*:*|*\\*)
      fail "The folder path contains one of  ,  '  :  \\  which the audio-cleanup filter
  cannot handle. Move this folder somewhere without those characters and run the
  installer again. Current path: $PKG_ROOT" ;;
  esac
}

# The Python that runs Sniper's own helpers: the app's environment once it exists,
# otherwise the Python among Sniper's own tools. Never /usr/bin/python3, which on a Mac
# without Apple's developer tools opens an "install developer tools" dialog.
sniper_python() {
  if [ -x "$APP_DIR/.venv/bin/python3" ] && python_ok "$APP_DIR/.venv/bin/python3"; then
    printf '%s' "$APP_DIR/.venv/bin/python3"; return 0
  fi
  find_python
}

# Installed and still whole enough to use: settings, the installer's completion receipt
# for this folder, and Sniper's own tools (someone may have removed ~/.project-sniper).
install_complete() {
  [ -f "$ENV_FILE" ] && receipt_ok installed "$PKG_ROOT" || return 1
  deps_paths && deps_ready
}

# One value from RELEASE.json ("components.node_floor" style dotted keys).
release_value() {
  local py
  py="$(sniper_python)" || fail "Sniper's own tools are not installed yet. Run install/install.command."
  "$py" -c 'import json,sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
for key in sys.argv[2].split("."):
    value = value[key]
print(" ".join(map(str, value)) if isinstance(value, list) else value)' "$RELEASE_JSON" "$1" \
    || fail "RELEASE.json has no $1; this folder is incomplete."
}

# hold_maintenance MODE LABEL BUSY-MESSAGE [this script's arguments...]
# Re-run this script while holding the install's maintenance lock
# (scripts/infra/sniper_lock.py): exclusive for installing, cleaning and
# removing; shared for anything that uses the install (every ./sniper command).
# The lock is held until this script and everything it started have exited.
hold_maintenance() {
  local mode="$1" label="$2" busy="$3" py
  shift 3
  [ "${SNIPER_LOCKED_PID:-}" = "$$" ] && return 0
  py="$(sniper_python)" || fail "Sniper's own tools are not installed yet. Run install/install.command
  (or double-click install/setup.command)."
  [ -f "$LOCK_TOOL" ] || fail "This folder is incomplete: $LOCK_TOOL is missing."
  mkdir -p "$STATE_DIR" || fail "Cannot create $STATE_DIR"
  export SNIPER_LOCKED_PID=$$
  exec "$py" "$LOCK_TOOL" exec --state-dir "$STATE_DIR" --mode "$mode" --label "$label" \
    --busy-message "$busy" -- /bin/bash "$SCRIPT_PATH" "$@"
}

. "$PKG_ROOT/install/lib/settings.sh"
. "$PKG_ROOT/install/lib/tools.sh"
. "$PKG_ROOT/install/lib/processes.sh"
. "$PKG_ROOT/install/lib/download.sh"
. "$PKG_ROOT/install/lib/runtime_tools.sh"

# Load this install's settings: the installer's data file (literally), then your
# own runtime/sniper.local.env (shell syntax, by design).
# The folder is always taken from where these scripts are, never from the settings
# file: after a move or copy the settings still name the old place, and acting on
# it could stop or delete another install. `load_env --moved-ok` (uninstall only)
# continues with this folder's own paths instead of refusing.
load_env() {
  local here="$PKG_ROOT" recorded
  [ -f "$ENV_FILE" ] || fail "Sniper is not set up yet. Run install/install.command first
  (or ask your Codex or Claude Code: set up Sniper)."
  settings_load "$ENV_FILE"
  if [ -f "$LOCAL_ENV" ]; then
    set -a; . "$LOCAL_ENV" || fail "runtime/sniper.local.env has an error (it is read as shell)."; set +a
  fi
  # Guided setup owns this optional connection. Read as literal data, never shell.
  # An empty key records an explicit disconnect and overrides older manual keys.
  if [ -f "$RUNTIME_DIR/deepgram.env" ]; then
    settings_load "$RUNTIME_DIR/deepgram.env" || fail "Reopen install/setup.command to repair the Deepgram connection."
  fi
  recorded="$PKG_ROOT"; PKG_ROOT="$here"; APP_DIR="$here"; export PKG_ROOT APP_DIR
  if [ "$recorded" != "$here" ] && [ "${1:-}" != "--moved-ok" ]; then
    fail "This folder was moved or copied after it was installed (installed at:
  $recorded). Run install/install.command once in its new place."
  fi
}

# The Node among Sniper's own tools must still be there (someone may have removed
# ~/.project-sniper); the installer puts it back.
require_installed_node() {
  local problem
  problem="$(node_problem "${SNIPER_NODE_PATH:-}" "$(release_value components.node_floor)")"
  [ -z "$problem" ] || fail "Sniper's own Node cannot be used: $problem.
  Run install/install.command again; it reinstalls Sniper's tools."
}

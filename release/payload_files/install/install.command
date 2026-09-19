#!/bin/bash
# Project Sniper — Mac installer.
#
#   install/install.command [--workspace FOLDER]
#
# Installs everything Sniper's commands need. Its own tools (Python, Node, ffmpeg,
# whisper.cpp, tesseract, yt-dlp, git) go to ~/.project-sniper/runtimes/, downloaded and
# checked against this release's lock (install/deps/). The Python environment and the
# JavaScript dependencies go in this folder, the rendering browser and speech model under
# runtime/. You talk to Sniper through your own Codex or Claude Code; this installs no
# copy of either and never touches your own Node, Python, Homebrew, conda, Codex or
# Claude installation or login.
#
# Safe to run again. Each step records what it finished with and the SHA-256 of
# what it produced; a step is redone when its inputs changed, it never finished,
# or its output no longer verifies. Your settings in runtime/sniper.local.env are
# never touched. It runs only while nothing else uses this install (a ./sniper
# command, an edit or render, the doctor, cleanup or uninstall).

. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
. "$PKG_ROOT/install/lib/steps.sh" || exit 1
. "$PKG_ROOT/install/lib/configure.sh" || exit 1

usage() { fail "Unknown option: $1  (usage: install.command [--workspace FOLDER])"; }
require_macos
require_safe_install_path
# Step 1 comes before the maintenance lock: that lock's helper runs on Sniper's own Python,
# which this step installs (with only macOS's own tools). The rerun under the lock skips it.
if [ "${SNIPER_LOCKED_PID:-}" != "$$" ]; then
  say "Project Sniper installer — $PKG_ROOT"
  step "1/8  Sniper's own tools (Python, Node, ffmpeg, Whisper, Tesseract, yt-dlp)"
  ensure_runtime_tools
fi
hold_maintenance exclusive "installer" "Sniper cannot be installed or repaired while one of its commands is
  running. Let running edits and renders finish, then run this again." "$@"

WORKSPACE_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --workspace) WORKSPACE_ARG="${2:-}"; shift 2 ;;
    *) usage "$1" ;;
  esac
done
trap 'printf "\nSTOPPED: interrupted. Run install/install.command again; it redoes only what did not finish.\n" >&2; log_line "interrupted"; exit 130' INT TERM
refuse_if_active_work "Installing now would replace tools it is using."
mkdir -p "$RUNTIME_DIR" "$STATE_DIR" "$RECEIPTS" "$LOG_DIR"
# "installed" is written only after the last step succeeds; an interrupted or failed
# run leaves it absent, so ./sniper refuses to run and setup resumes the installer.
clear_receipt installed
log_line "install started"
# The Python environment records the folder it was made in. If this folder was moved
# or copied since, redo that step.
if [ -f "$RECEIPTS/location" ] && ! receipt_ok location "$PKG_ROOT"; then
  say "This folder was moved or copied since it was installed; redoing the step that records its location."
  clear_receipt venv; rm -rf "$APP_DIR/.venv"
fi
write_receipt location "$PKG_ROOT"

# ---------------------------------------------------------------- 1. Sniper's own tools
verify_runtime_tools
use_runtime_tools
link_runtime_bin

# ------------------------------------------------------- 2-6. dependencies and downloads
step "2/8  JavaScript dependencies (for Sniper's scripts)"
npm_step "JavaScript dependencies" "$APP_DIR" npm-app
step "3/8  Rendering-project dependencies"
npm_step "rendering-project dependencies" "$APP_DIR/templates/motion" npm-motion
step "4/8  Python environment from the pinned, hash-checked list"
python_step
step "5/8  Rendering browser"
browser_step
step "6/8  Speech model"
model_step

# ------------------------------------------------------------ 7. configuration
step "7/8  Configuration"
write_settings
verify_settings
say "Video projects: $SNIPER_WORKSPACE_ROOT"

# ------------------------------------------------------------ 8. render runtime
step "8/8  Rendering runtime"
# native_runtime.py builds under runtime-build.lock and removes what an interrupted
# build left; --repair also rebuilds a finished runtime that no longer verifies.
# This installer holds the maintenance lock exclusively, so no render uses it now.
RUNTIME_RESULT="$( load_env; cd "$APP_DIR" && PYTHONPATH="$APP_DIR/scripts/producer" "$APP_DIR/.venv/bin/python3" \
    "$APP_DIR/scripts/producer/studio/native_runtime.py" --repair )" \
  || fail "The rendering runtime did not build from its shipped patch set."
say "Rendering runtime — ${RUNTIME_RESULT%%$'\t'*}"
write_receipt installed "$PKG_ROOT"
log_line "install finished"

# In a Terminal window, offer the optional Deepgram connection (it needs a hidden prompt).
if [ -t 0 ] && [ -t 1 ]; then
  "$PKG_ROOT/install/setup.command" --connections --if-needed || exit $?
fi

say ""
"$PKG_ROOT/install/doctor.command"
DOCTOR=$?
say ""
if [ "$DOCTOR" -ne 0 ]; then
  say "Installed, but the checks above report something still to do."
  exit "$DOCTOR"
fi
say "Sniper is ready. In Codex or Claude Code, with this folder open, ask for your first edit,"
say "for example: Make a trim-only clean cut of ~/Movies/test-clip.mp4."
exit 0

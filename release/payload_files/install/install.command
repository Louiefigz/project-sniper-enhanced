#!/bin/bash
# Project Sniper — Mac installer.
#
#   install/install.command [--provider codex|claude] [--workspace FOLDER]
#
# Installs what Sniper needs inside this folder: the app's dependencies and
# Python environment under app/, and the rendering browser, speech model and
# pinned provider CLIs under runtime/. It does not change your own Node, Python,
# Homebrew, Codex or Claude installation, or your existing Codex/Claude login.
#
# Safe to run again. Each step records what it finished with and the SHA-256 of
# what it produced; a step is redone when its inputs changed, it never finished,
# or its output no longer verifies. Your settings in runtime/sniper.local.env are
# never touched. It runs only while nothing else uses this install (the app, an
# editor window, an edit or render, the doctor, cleanup or uninstall).

. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
. "$PKG_ROOT/install/lib/steps.sh" || exit 1
. "$PKG_ROOT/install/lib/configure.sh" || exit 1

usage() { fail "Unknown option: $1  (usage: install.command [--provider codex|claude] [--workspace FOLDER])"; }
require_macos
require_safe_install_path
hold_maintenance exclusive "installer" "Sniper cannot be installed, repaired or switched while it is in use.
  Stop the app (install/stop.command), close any Sniper editor window and let running edits
  finish, then run this again." "$@"

PROVIDER_ARG=""; WORKSPACE_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --provider) PROVIDER_ARG="${2:-}"; shift 2 ;;
    --workspace) WORKSPACE_ARG="${2:-}"; shift 2 ;;
    *) usage "$1" ;;
  esac
done
trap 'printf "\nSTOPPED: interrupted. Run install/install.command again; it redoes only what did not finish.\n" >&2; log_line "interrupted"; exit 130' INT TERM
refuse_if_active_work "Installing now would replace tools it is using."
mkdir -p "$RUNTIME_DIR" "$STATE_DIR" "$RECEIPTS" "$LOG_DIR"
log_line "install started"
# The Python environment and the app build record the folder they were made in.
# If this folder was moved or copied since, redo exactly those two steps.
if [ -f "$RECEIPTS/location" ] && ! receipt_ok location "$PKG_ROOT"; then
  say "This folder was moved or copied since it was installed; redoing the steps that record its location."
  clear_receipt venv; clear_receipt build; rm -rf "$APP_DIR/.venv"
fi
write_receipt location "$PKG_ROOT"

say "Project Sniper installer — $PKG_ROOT"

# ---------------------------------------------------------------- 1. prerequisites
step "1/10  Checking the tools you install yourself"
select_node
PYTHON_BIN="$(find_python)" || {
  say "Python 3.12 or newer is required (numpy and scipy in this release need 3.12)."
  say "  Download it from https://www.python.org/downloads/macos/"
  fail "Python 3.12+ is missing."; }
PY_VER="$("$PYTHON_BIN" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')"
say "Python $PY_VER — ok (this release was tested with $(release_value components.python_tested))"
check_external_tools
link_runtime_bin

# ------------------------------------------------------- 2-7. dependencies and downloads
step "2/10  Application dependencies"
npm_step "app dependencies" "$APP_DIR" npm-app
step "3/10  Rendering-project dependencies"
npm_step "rendering-project dependencies" "$APP_DIR/templates/motion" npm-motion
step "4/10  Python environment from the pinned, hash-checked list"
python_step
step "5/10  Rendering browser"
browser_step
step "6/10  Speech model"
model_step
step "7/10  Pinned Codex and Claude CLIs (kept inside this folder)"
cli_step

# ------------------------------------------------------------ 8. configuration
step "8/10  Configuration"
choose_provider
write_settings
verify_settings
[ -f "$APP_DIR/.env.local" ] || cp "$APP_DIR/.env.local.example" "$APP_DIR/.env.local"
say "Editor brain: $PROVIDER   ·   Video projects: $SNIPER_WORKSPACE_ROOT"

# ------------------------------------------------------------ 9. render runtime
step "9/10  Rendering runtime"
# native_runtime.py builds under runtime-build.lock and removes what an interrupted
# build left; --repair also rebuilds a finished runtime that no longer verifies.
# This installer holds the maintenance lock exclusively, so no render uses it now.
( load_env; cd "$APP_DIR" && PYTHONPATH="$APP_DIR/scripts/producer" "$APP_DIR/.venv/bin/python3" \
    "$APP_DIR/scripts/producer/studio/native_runtime.py" --repair >/dev/null ) \
  || fail "The rendering runtime did not build from its shipped patch set."
say "Rendering runtime — verified"

# ------------------------------------------------------------ 10. production app
build_step() {
  local key why record="$RECEIPTS/build.tree.json"
  key="$(release_value version)|node-$NODE_VERSION@$NODE_BIN|deps-$(sha "$RECEIPTS/npm-app.tree.json")"
  if receipt_ok build "$key" && [ -f "$APP_DIR/.next/BUILD_ID" ]; then
    why="$(tree_check "$APP_DIR/.next" "$record" cache)" && { say "App build — up to date (verified)"; return 0; }
    say "App build — changed since it was built ($why); rebuilding"
  fi
  clear_receipt build
  if ! ( load_env; cd "$APP_DIR" && npm_cli run build ) >> "$LOG_DIR/build.log" 2>&1; then
    tail -15 "$LOG_DIR/build.log" >&2
    fail "Building the app failed (the lines above are from $LOG_DIR/build.log).
  Run the installer again; if it fails the same way, run install/diagnostics.command."
  fi
  [ -f "$APP_DIR/.next/BUILD_ID" ] || fail "The app build finished without a build id."
  tree_record "$APP_DIR/.next" "$record" cache
  write_receipt build "$key"; say "App build — done ($(cat "$APP_DIR/.next/BUILD_ID"))"
}
step "10/10  Building the app (no network needed)"
build_step
log_line "install finished"

say ""
"$PKG_ROOT/install/doctor.command"
DOCTOR=$?
say ""
if [ "$DOCTOR" -ne 0 ]; then
  say "Installed, but the checks above report something still to do."
  say "If the editor brain is among the failures, sign in next:"
fi
say "  install/sign-in.command         (signs in to $PROVIDER inside this folder)"
say "Then open START-HERE.html."
exit "$DOCTOR"

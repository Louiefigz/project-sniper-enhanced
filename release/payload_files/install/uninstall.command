#!/bin/bash
# Project Sniper — remove this install. Your video projects are not touched.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
[ -f "$ENV_FILE" ] && load_env --moved-ok
WORKSPACE="${SNIPER_WORKSPACE_ROOT:-$HOME/ProjectSniper}"
say "This removes only what the installer created inside this folder:"
say "  $RUNTIME_DIR   (browser, speech model, pinned CLIs, settings, Sniper's logins)"
say "  $APP_DIR/node_modules, $APP_DIR/templates/motion/node_modules"
say "  $APP_DIR/.venv, $APP_DIR/.next"
say ""
say "It does NOT touch your video projects ($WORKSPACE), your own Node, Python,"
say "Homebrew, ffmpeg or whisper install, or your own Codex/Claude CLI and login."
if [ "${1:-}" != "--yes" ]; then printf 'Type REMOVE to continue: '; read -r answer
  [ "$answer" = "REMOVE" ] || { say "Nothing was removed."; exit 0; }; fi
# A background edit or render keeps running after the app stops, and would fail
# half-way if its tools were removed underneath it.
ACTIVE="$(active_work_pids | tr '\n' ' ')"
if [ -n "${ACTIVE// }" ]; then
  fail "An edit or render from this install is still running: $(describe_pids $ACTIVE).
  Nothing was removed. Let it finish (or cancel it from its project), then run this again."
fi
[ -x "$PKG_ROOT/install/stop.command" ] && [ -f "$ENV_FILE" ] && "$PKG_ROOT/install/stop.command" >/dev/null 2>&1
# Sign out of the logins made *for Sniper* using its own pinned CLIs and settings,
# so no credential is left behind in the Keychain or on disk.
if [ -x "$CLI_BIN/claude" ]; then CLAUDE_CONFIG_DIR="$CLAUDE_CONFIG_DIR_LOCAL" "$CLI_BIN/claude" auth logout >/dev/null 2>&1; fi
if [ -x "$CLI_BIN/codex" ]; then CODEX_HOME="$CODEX_HOME_LOCAL" "$CLI_BIN/codex" logout >/dev/null 2>&1; fi
rm -rf "$RUNTIME_DIR" "$APP_DIR/node_modules" "$APP_DIR/templates/motion/node_modules" \
       "$APP_DIR/.venv" "$APP_DIR/.next" "$APP_DIR/templates/motion/.sniper-native-runtime"
say "Removed. Delete this folder to finish, or run install/install.command to reinstall."

#!/bin/bash
# Project Sniper — remove this install. Your video projects are not touched.
#
#   install/uninstall.command [--yes] [--keep-logins]
#
# Order: take the install for itself (nothing else may be using it), stop the app,
# sign out the logins made FOR SNIPER, then remove what the installer created.
# If stopping the app or a sign-out fails, nothing is removed and it exits 1, so
# you can fix the cause and run it again. --keep-logins skips signing out (for a
# broken CLI) and says exactly what stays behind.
#
# Kept on purpose, so a reinstall in this folder picks them up: your own settings
# (runtime/sniper.local.env, app/.env.local) and the export-recovery history
# (app/templates/motion/.sniper-native-runtime/native-export-history). Never
# touched: your video projects, your own Node/Python/Homebrew/ffmpeg/whisper, your
# global Codex and Claude CLIs, ~/.codex, ~/.claude, ~/.claude.json and any
# Keychain item other than Sniper's own Claude login.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
[ -f "$ENV_FILE" ] && load_env --moved-ok
hold_maintenance exclusive "uninstall" "Sniper cannot be removed while it is in use. Stop the app
  (install/stop.command), close any Sniper editor window and let running edits finish." "$@"
YES=0; KEEP_LOGINS=0
for arg in "$@"; do
  case "$arg" in --yes) YES=1 ;; --keep-logins) KEEP_LOGINS=1 ;; *) fail "Unknown option: $arg" ;; esac
done
WORKSPACE="${SNIPER_WORKSPACE_ROOT:-$HOME/ProjectSniper}"
RUNTIME_CACHE="$APP_DIR/templates/motion/.sniper-native-runtime"
REMOVE=("$APP_DIR/node_modules" "$APP_DIR/templates/motion/node_modules" "$APP_DIR/.venv" "$APP_DIR/.next")
for entry in "$RUNTIME_DIR"/* "$RUNTIME_DIR"/state/* "$RUNTIME_CACHE"/*; do
  case "$entry" in
    "$RUNTIME_DIR/sniper.local.env"|"$RUNTIME_DIR/state"|"$RUNTIME_DIR"/state/*.lock) continue ;;
    "$RUNTIME_CACHE/native-export-history"|"$RUNTIME_CACHE/.locks") continue ;;
  esac
  [ -e "$entry" ] || [ -L "$entry" ] && REMOVE+=("$entry")
done

say "This removes what the installer created inside this folder:"
say "  runtime/ (browser, speech model, pinned CLIs, Sniper's logins, logs, receipts)"
say "  app/node_modules, app/templates/motion/node_modules, app/.venv, app/.next,"
say "  and the render runtime and caches in app/templates/motion/.sniper-native-runtime"
say "It keeps, so a reinstall here picks them up: runtime/sniper.local.env and"
say "app/.env.local (your settings) and .sniper-native-runtime/native-export-history"
say "(what an interrupted export needs to resume)."
say "It does NOT touch your video projects ($WORKSPACE), your own Node, Python,"
say "Homebrew, ffmpeg or whisper install, or your own Codex/Claude CLI and login."
if [ "$YES" != 1 ]; then printf 'Type REMOVE to continue: '; read -r answer
  [ "$answer" = "REMOVE" ] || { say "Nothing was removed."; exit 0; }; fi

# A background edit or render keeps running after the app stops, and would fail
# half-way if its tools were removed underneath it.
refuse_if_active_work "Nothing was removed."
if [ -f "$STATE_DIR/app.pid" ]; then
  out="$("$PKG_ROOT/install/stop.command" 2>&1)" || fail "Stopping the app failed, so nothing was removed:
  $out"
fi

cli() { PATH="$RUNTIME_BIN:$PATH" CODEX_HOME="$CODEX_HOME_LOCAL" CLAUDE_CONFIG_DIR="$CLAUDE_CONFIG_DIR_LOCAL" "$CLI_BIN/$@"; }
# Sniper's Codex login lives in runtime/codex-home; Claude's in a Keychain item
# named after runtime/claude-config. Each is signed out with Sniper's own CLI, then
# checked, and a login that is still there stops the removal.
codex_signed_in() {  # 0 signed in, 1 not, 2 cannot tell
  local out rc=0
  out="$(cli codex login status 2>&1)" || rc=$?
  [ "$rc" = 0 ] && return 0
  case "$out" in *"Not logged in"*) return 1 ;; esac
  return 2
}
claude_signed_in() {
  local out rc=0
  out="$(cli claude auth status --json 2>&1)" || rc=$?
  case "$out" in *'"loggedIn": true'*|*'"loggedIn":true'*) return 0 ;; *'"loggedIn": false'*|*'"loggedIn":false'*) return 1 ;; esac
  return 2
}
sign_out() {  # provider logout-args...
  local provider="$1" state out rc=0
  shift
  "${provider}_signed_in"; state=$?
  [ "$state" = 1 ] && { say "Sniper's $provider login: not signed in."; return 0; }
  [ "$state" = 2 ] && fail "Could not check Sniper's $provider login, so nothing was removed.
  Reinstall the CLIs (install/install.command) and run this again, or run it with
  --keep-logins to remove everything else and leave that login in place."
  out="$(cli "$provider" "$@" 2>&1)" || rc=$?
  "${provider}_signed_in"; state=$?
  [ "$state" = 1 ] || fail "Signing out of Sniper's $provider login failed (exit $rc): $(printf '%s' "$out" | head -3)
  Nothing was removed. Check your connection and run this again, or use --keep-logins."
  say "Sniper's $provider login: signed out."
}
if [ "$KEEP_LOGINS" = 1 ]; then
  warn "--keep-logins: Sniper's logins were not signed out. Removing runtime/ deletes the Codex
  login file; a Claude login made for Sniper stays in your Keychain as an item whose name
  starts with 'Claude Code-credentials-' — delete it in Keychain Access if you want."
else
  [ -x "$CLI_BIN/codex" ] && sign_out codex logout
  [ -x "$CLI_BIN/claude" ] && sign_out claude auth logout
  [ -x "$CLI_BIN/claude" ] || [ ! -d "$CLAUDE_CONFIG_DIR_LOCAL" ] \
    || warn "Sniper's Claude CLI is not installed here, so a Claude login made for Sniper could
  not be checked; if one exists it stays in your Keychain ('Claude Code-credentials-…')."
fi

rm -rf "${REMOVE[@]}" 2>/dev/null
LEFT=()
for path in "${REMOVE[@]}"; do [ -e "$path" ] || [ -L "$path" ] && LEFT+=("$path"); done
if [ ${#LEFT[@]} -gt 0 ]; then
  fail "These could not be removed (permissions, or a file in use):
$(printf '    %s\n' "${LEFT[@]}")
  Run this again after closing whatever uses them."
fi
log_line "uninstalled"
say "Removed. Kept: your settings (runtime/sniper.local.env and app/.env.local, if you made"
say "them) and the export-recovery history. Run install/install.command to reinstall here, or"
say "delete this folder to finish — that also deletes what was kept, so copy it first if needed."

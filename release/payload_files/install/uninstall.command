#!/bin/bash
# Project Sniper — remove what the installer created. Your video projects are not touched.
#
#   install/uninstall.command [--yes]
#
# Takes the install for itself (nothing else may be using it), then removes what the
# installer created. If something is still running inside this folder, nothing is
# removed and it exits 1, so you can let it finish and run this again.
#
# Kept on purpose, so a reinstall in this folder picks them up: your own settings
# (runtime/sniper.local.env), your video projects (projects/ by default), which folder
# they are in (runtime/workspace.env) and the
# export-recovery history (templates/motion/.sniper-native-runtime/native-export-history).
# Sniper's own tools in ~/.project-sniper are removed when no other Sniper install uses
# them. Never touched: your own Node/Python/Homebrew/ffmpeg/whisper, and your own Codex or
# Claude Code and their logins (Sniper never installs or signs in to either).
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
[ -f "$ENV_FILE" ] && load_env --moved-ok
hold_maintenance exclusive "uninstall" "Sniper cannot be removed while one of its commands is running.
  Let running edits and renders finish, then run this again." "$@"
YES=0
for arg in "$@"; do
  case "$arg" in --yes) YES=1 ;; *) fail "Unknown option: $arg" ;; esac
done
WORKSPACE="$(kept_workspace)"; WORKSPACE="${WORKSPACE:-$PKG_ROOT/projects}"
# runtime/sniper.local.env may point the workspace elsewhere; it is kept and still wins on a
# reinstall, so name that folder (the kept record stays the installer's own value).
SHOWN="$WORKSPACE"
[ -f "$ENV_FILE" ] && [ -f "$LOCAL_ENV" ] && [ -n "${SNIPER_WORKSPACE_ROOT:-}" ] \
  && [ "$SNIPER_WORKSPACE_ROOT" != "$(settings_value SNIPER_WORKSPACE_ROOT 2>/dev/null)" ] && SHOWN="$SNIPER_WORKSPACE_ROOT"
RUNTIME_CACHE="$APP_DIR/templates/motion/.sniper-native-runtime"
REMOVE=("$APP_DIR/node_modules" "$APP_DIR/templates/motion/node_modules" "$APP_DIR/.venv" "$APP_DIR/.next")
for entry in "$RUNTIME_DIR"/* "$RUNTIME_DIR"/state/* "$RUNTIME_CACHE"/*; do
  case "$entry" in
    "$RUNTIME_DIR/sniper.local.env"|"$KEPT_WORKSPACE"|"$RUNTIME_DIR/state"|"$RUNTIME_DIR"/state/*.lock) continue ;;
    "$RUNTIME_CACHE/native-export-history"|"$RUNTIME_CACHE/.locks") continue ;;
  esac
  [ -e "$entry" ] || [ -L "$entry" ] && REMOVE+=("$entry")
done

say "This removes what the installer created inside this folder:"
say "  runtime/ (rendering browser, speech model, logs, receipts, the Deepgram connection)"
say "  node_modules, templates/motion/node_modules, .venv,"
say "  and the render runtime and caches in templates/motion/.sniper-native-runtime"
say "It keeps, so a reinstall here picks them up: runtime/sniper.local.env (your settings),"
say "runtime/workspace.env (which folder your video projects are in) and"
say ".sniper-native-runtime/native-export-history (what an interrupted export needs to resume)."
say "It also removes Sniper's own tools (~/.project-sniper) unless another Sniper install uses them."
say "It does NOT touch your video projects ($SHOWN), your own Node, Python,"
say "Homebrew, ffmpeg or whisper install, or your own Codex or Claude Code and their logins."
if [ "$YES" != 1 ]; then printf 'Type REMOVE to continue: '; read -r answer
  [ "$answer" = "REMOVE" ] || { say "Nothing was removed."; exit 0; }; fi

# A background edit or render would fail half-way if its tools were removed underneath it.
refuse_if_active_work "Nothing was removed."

settings_write "$KEPT_WORKSPACE" "PKG_ROOT=$PKG_ROOT" "SNIPER_WORKSPACE_ROOT=$WORKSPACE"
rm -rf "${REMOVE[@]}" 2>/dev/null
LEFT=()
for path in "${REMOVE[@]}"; do [ -e "$path" ] || [ -L "$path" ] && LEFT+=("$path"); done
if [ ${#LEFT[@]} -gt 0 ]; then
  fail "These could not be removed (permissions, or a file in use):
$(printf '    %s\n' "${LEFT[@]}")
  Run this again after closing whatever uses them."
fi
deps_unregister_and_prune
log_line "uninstalled"
say "Removed. Kept: your settings (runtime/sniper.local.env, if you made one), your video projects"
say "and which folder they are in, and the export-recovery history. Run install/install.command to reinstall here. Deleting this"
say "folder also deletes what was kept — including your projects if they are in projects/ —"
say "so move them first."

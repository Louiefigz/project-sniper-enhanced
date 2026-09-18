#!/bin/bash
# Project Sniper — remove this install. Your video projects are NOT touched.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
say "This removes only what the installer created inside this package:"
say "  $RUNTIME_DIR                (browser, speech model, pinned CLI, settings)"
say "  $APP_DIR/node_modules"
say "  $APP_DIR/templates/motion/node_modules"
say "  $APP_DIR/.venv"
say ""
say "It does NOT touch:"
say "  your video projects (${SNIPER_WORKSPACE_ROOT:-$HOME/ProjectSniper})"
say "  your own Node, Python, Homebrew, ffmpeg or whisper install"
say "  your global Codex or Claude CLI and their logins"
printf 'Type REMOVE to continue: '
read -r answer
[ "$answer" = "REMOVE" ] || { say "Nothing was removed."; exit 0; }
rm -rf "$RUNTIME_DIR" "$APP_DIR/node_modules" "$APP_DIR/templates/motion/node_modules" \
       "$APP_DIR/.venv"
say "Removed. Delete this folder to finish, or run install.command to reinstall."

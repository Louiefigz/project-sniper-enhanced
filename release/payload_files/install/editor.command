#!/bin/bash
# Project Sniper — open your editor brain in the app folder, the main way to edit.
# Runs the pinned Codex or Claude CLI with this package's own settings, so your
# normal Codex/Claude setup is not used or changed.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
cd "$APP_DIR" || exit 1
case "${1:-$SNIPER_PROVIDER}" in
  codex)  exec "$CLI_BIN/codex" ;;
  claude) exec "$CLI_BIN/claude" ;;
  *) fail "Usage: install/editor.command [codex|claude]" ;;
esac

#!/bin/bash
# Project Sniper — switch the editor brain between Codex and Claude, for the
# whole install: the app, the editor window, sign-in, the doctor and every edit.
#   install/use-provider.command codex|claude
# It reruns the installer (which skips every finished step), so the app must be
# stopped first; restart it afterwards so it runs on the new choice.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
case "${1:-}" in codex|claude) ;; *) fail "Usage: install/use-provider.command codex|claude" ;; esac
exec "$PKG_ROOT/install/install.command" --provider "$1"

#!/bin/bash
# Project Sniper — switch the editor brain between Codex and Claude.
#   install/use-provider.command codex|claude
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
case "$1" in codex|claude) ;; *) fail "Usage: install/use-provider.command codex|claude" ;; esac
exec "$PKG_ROOT/install/install.command" --provider "$1"

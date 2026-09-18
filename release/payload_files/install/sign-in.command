#!/bin/bash
# Project Sniper — sign in to your Codex or Claude subscription for Sniper.
#
#   install/sign-in.command            (the provider you chose at install)
#   install/sign-in.command codex|claude
#
# Uses this package's pinned CLI and its own settings folder under runtime/, so
# your existing Codex or Claude login and settings are left exactly as they are.
# Signing in to the provider this install does not use is allowed (to prepare a
# switch); it does not change which one Sniper uses.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
PROVIDER="${1:-$SNIPER_PROVIDER}"
case "$PROVIDER" in codex|claude) ;; *) fail "Usage: install/sign-in.command [codex|claude]" ;; esac
hold_maintenance shared "sign-in ($PROVIDER)" "Sniper is being installed, repaired, cleaned or removed
  right now; sign in when that has finished." "$@"
case "$PROVIDER" in
  codex)
    say "Signing in to Codex with your ChatGPT subscription (settings: $CODEX_HOME)."
    "$CLI_BIN/codex" -c 'forced_login_method="chatgpt"' login ;;
  claude)
    say "Signing in to Claude with your Claude subscription (settings: $CLAUDE_CONFIG_DIR)."
    say "macOS keeps this login in your Keychain as its own item, separate from any"
    say "Claude login you already have. install/uninstall.command signs it out."
    "$CLI_BIN/claude" --settings '{"forceLoginMethod":"claudeai"}' auth login ;;
esac
say ""
if [ "$PROVIDER" != "$SNIPER_PROVIDER" ]; then
  say "Signed in to $PROVIDER. This install still uses $SNIPER_PROVIDER; switch with"
  say "install/use-provider.command $PROVIDER (stop the app first)."
fi
"$PKG_ROOT/install/doctor.command" --provider-only --provider "$PROVIDER"

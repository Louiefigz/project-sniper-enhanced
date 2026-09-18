#!/bin/bash
# Project Sniper — open your editor brain in the app folder, the main way to edit.
#
#   install/editor.command            (the provider this install uses)
#
# Runs the pinned Codex or Claude CLI with this package's own settings, so your
# normal Codex/Claude setup is not used or changed. The CLI gets the same
# provider, model and reasoning settings as the app and every edit it starts.
# Naming the other provider is refused rather than half-obeyed: the app and its
# background edits would keep using the installed one. Switch the whole install
# with install/use-provider.command instead.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
if [ ! -f "$ENV_FILE" ]; then
  "$PKG_ROOT/install/install.command" || exit $?
fi
load_env
case "${1:-}" in
  ''|"$SNIPER_PROVIDER") ;;
  codex|claude)
    fail "This install's editor brain is $SNIPER_PROVIDER. An editor window on $1 would disagree with
  the app and the background edits it starts, which keep using $SNIPER_PROVIDER.
  To switch everything to $1:  install/stop.command, then install/use-provider.command $1,
  then install/sign-in.command." ;;
  *) fail "Usage: install/editor.command [codex|claude]" ;;
esac
hold_maintenance shared "editor window ($SNIPER_PROVIDER)" "Sniper is being installed, repaired, cleaned or
  removed right now; open the editor again when that has finished." "$@"
cd "$APP_DIR" || exit 1
# The editor never sees a paid API key (a Text Review key lives in sniper.local.env);
# DEEPGRAM_API_KEY stays, for a Deepgram run the operator explicitly authorizes.
NO_KEYS=(env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u OPENAI_API_KEY -u CLAUDE_CODE_OAUTH_TOKEN)
case "$SNIPER_PROVIDER" in
  codex)  exec "${NO_KEYS[@]}" "$CLI_BIN/codex" -c 'forced_login_method="chatgpt"' --model="$SNIPER_CODEX_MODEL" \
            -c "model_reasoning_effort=\"$SNIPER_CODEX_REASONING\"" ;;
  claude)
    # Project and local settings only, and no CLAUDE.md from the folders above the app
    # (your ~/CLAUDE.md or ~/.claude/CLAUDE.md when the package sits in your home folder).
    settings="$("$APP_DIR/.venv/bin/python3" -B "$PKG_ROOT/install/lib/editor_settings.py" "$APP_DIR")" \
      || fail "Could not prepare the editor's settings; run install/doctor.command."
    exec "${NO_KEYS[@]}" "$CLI_BIN/claude" --setting-sources project,local --settings "$settings" \
      --model="$SNIPER_CLAUDE_MODEL" ;;
esac

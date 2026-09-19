#!/bin/bash
# Guided first-run connections. Also safe to reopen to replace/remove a key.
# The connection writer holds an exclusive maintenance lock in a child process.
# That lock is released before launching an editor; edits must not inherit it.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1

MODE="${1:-}"
case "$MODE" in
  ''|--finish-install|--connections) ;;
  *) fail "Double-click setup.command to connect Sniper." ;;
esac

# Settings are written at step 8 of 10, so their presence does not mean the install
# finished. The installer writes the "installed" receipt (for this folder) only after
# its last step; without it — or without Sniper's own tools — resume the installer,
# which redoes only unfinished steps.
# The --connections and --finish-install modes never start the installer themselves.
if ! install_complete; then
  [ -z "$MODE" ] || fail "Installation has not finished. Run install/install.command first."
  [ -f "$ENV_FILE" ] && say "The last installation did not finish (or this folder moved); resuming it."
  "$PKG_ROOT/install/install.command" || exit $?
  exec "$PKG_ROOT/install/editor.command"
fi

load_env

# Only this short-lived child owns the connection-write lock. The installer may
# already own it; the existing lock helper verifies inherited descriptors.
if [ "$MODE" = --connections ]; then
  hold_maintenance exclusive "connection setup" "Close Sniper's editor and stop the app with
  install/stop.command before changing connections. Then reopen install/setup.command." "$@"
  PYTHON_BIN="$(sniper_python)" || fail "Run install/install.command to repair Python."
  shift
  exec "$PYTHON_BIN" "$PKG_ROOT/install/lib/deepgram_setup.py" "$@"
fi

if [ ! -t 0 ]; then
  fail "Setup needs a Terminal window. Double-click install/setup.command."
fi

say "Welcome to Project Sniper"
say "We will sign you in, offer optional Deepgram transcription, and check your setup."

step "Sign in to your $SNIPER_PROVIDER subscription"
if "$PKG_ROOT/install/doctor.command" --provider-only >/dev/null 2>&1; then
  say "Already signed in."
else
  say "Follow the sign-in instructions in your browser, then return here."
  "$PKG_ROOT/install/sign-in.command" || {
    say "Sign-in or its check did not finish. Reopen install/setup.command to retry."
    exit 1
  }
fi

if [ "$MODE" = --finish-install ]; then
  "$PKG_ROOT/install/setup.command" --connections --if-needed || exit $?
else
  "$PKG_ROOT/install/setup.command" --connections || exit $?
fi
load_env

step "Check this installation"
"$PKG_ROOT/install/doctor.command" || {
  say "Setup is not ready yet. Follow the failed checks above, then reopen install/setup.command."
  exit 1
}
say "Ready. Tell Sniper: Help me make my first edit from my own video."
if [ "$MODE" = --finish-install ]; then
  say "Next, double-click install/editor.command to open your configured $SNIPER_PROVIDER editor."
  exit 0
fi
say "Opening your configured $SNIPER_PROVIDER editor."
exec "$PKG_ROOT/install/editor.command"

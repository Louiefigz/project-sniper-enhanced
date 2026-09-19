#!/bin/bash
# Project Sniper — set up by double-click, and connect or change the optional Deepgram key.
#
#   install/setup.command                 install (or finish an interrupted install), offer Deepgram, check
#   install/setup.command --connections   connect, replace or remove the Deepgram key
#
# You can also ask your Codex or Claude Code, with this folder open, to "set up Sniper":
# it runs install/install.command. The Deepgram key is entered here, in a Terminal window,
# so it never goes into a conversation. The connection writer holds an exclusive
# maintenance lock in a child process.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1

MODE="${1:-}"
case "$MODE" in
  ''|--connections) ;;
  *) fail "Double-click install/setup.command to set up Sniper." ;;
esac

# The installer writes the "installed" receipt (for this folder) only after its last step;
# without it — or without Sniper's own tools — resume the installer, which redoes only
# unfinished steps. It offers the Deepgram connection itself when it runs in a Terminal.
if ! install_complete; then
  [ -z "$MODE" ] || fail "Installation has not finished. Run install/install.command first."
  [ -f "$ENV_FILE" ] && say "The last installation did not finish, this folder moved, or Sniper's own tools are missing;
  resuming the installation."
  exec "$PKG_ROOT/install/install.command"
fi

load_env

# Only this short-lived child owns the connection-write lock.
if [ "$MODE" = --connections ]; then
  hold_maintenance exclusive "connection setup" "A Sniper command is running. Let it finish, then reopen
  install/setup.command." "$@"
  PYTHON_BIN="$(sniper_python)" || fail "Run install/install.command to repair Python."
  shift
  exec "$PYTHON_BIN" "$PKG_ROOT/install/lib/deepgram_setup.py" "$@"
fi

if [ ! -t 0 ]; then
  fail "Setup needs a Terminal window. Double-click install/setup.command."
fi

say "Project Sniper is installed."
"$PKG_ROOT/install/setup.command" --connections || exit $?
load_env

step "Check this installation"
"$PKG_ROOT/install/doctor.command" || {
  say "Setup is not ready yet. Follow the failed checks above, then reopen install/setup.command."
  exit 1
}
say "Ready. Open this folder in Codex or Claude Code and ask for your first edit."

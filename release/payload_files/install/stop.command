#!/bin/bash
# Project Sniper — stop the local app. Background edits keep running on purpose.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
if [ -f "$STATE_DIR/app.pid" ] && kill -0 "$(cat "$STATE_DIR/app.pid")" 2>/dev/null; then
  kill -TERM "$(cat "$STATE_DIR/app.pid")" 2>/dev/null
  say "Stop signal sent. The supervisor shuts the whole app group down."
else
  say "The app does not appear to be running."
fi
rm -f "$STATE_DIR/app.pid"
say "An edit that was already running continues in the background and can be"
say "resumed from the project after you start the app again."

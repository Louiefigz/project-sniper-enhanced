#!/bin/bash
# Project Sniper — stop the local app. A background edit that is already running
# keeps running on purpose; it can be resumed from its project later.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
# Stopping must work even when a setting is wrong or the folder was moved: the
# supervisor is identified by its process and folder, never by the settings.
load_env --moved-ok
PORT="${SNIPER_PORT:-3000}"
PIDFILE="$STATE_DIR/app.pid"
PID="$(cat "$PIDFILE" 2>/dev/null)"
if [ -z "$PID" ]; then say "Sniper is not running (no record of a start)."; exit 0; fi
if ! pid_is_our_supervisor "$PID"; then
  rm -f "$PIDFILE"
  say "The recorded process ($PID) is no longer this install's app, so nothing was signalled."
  HOLDERS="$(port_listener_pids)"
  [ -n "$HOLDERS" ] && say "Port $PORT is held by pid(s) $HOLDERS, which this script did not start."
  exit 0
fi
kill -TERM "$PID"
for _ in $(seq 1 30); do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
if kill -0 "$PID" 2>/dev/null; then fail "The app did not stop within 30 seconds (pid $PID)."; fi
rm -f "$PIDFILE"
say "Stopped. A render or edit that was already running continues in the background."

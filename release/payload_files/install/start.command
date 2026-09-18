#!/bin/bash
# Project Sniper — start the local app (loopback only) and open it.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
PORT="${SNIPER_PORT:-3000}"
PIDFILE="$STATE_DIR/app.pid"
[ -f "$APP_DIR/.next/BUILD_ID" ] || fail "The app has not been built. Run install/install.command."
BUILD_ID="$(cat "$APP_DIR/.next/BUILD_ID")"
PROBE="http://127.0.0.1:$PORT/_next/static/$BUILD_ID/_buildManifest.js"

# Serving *this* build's manifest proves the listener is this install, not
# some other program that happens to hold the port.
serving_this_build() { [ "$(curl -s -o /dev/null -m 3 -w '%{http_code}' "$PROBE")" = 200 ]; }

if pid_is_our_supervisor "$(cat "$PIDFILE" 2>/dev/null)"; then
  if serving_this_build; then say "Already running: http://127.0.0.1:$PORT"; open "http://127.0.0.1:$PORT"; exit 0; fi
  fail "A Sniper supervisor is running but not serving yet. Wait a moment, or run install/stop.command."
fi
HOLDERS="$(port_listener_pids)"
if [ -n "$HOLDERS" ]; then
  names="$(for p in $HOLDERS; do printf '%s (pid %s) ' "$(ps -o comm= -p "$p" | xargs basename)" "$p"; done)"
  fail "Port $PORT is already in use by: $names
  Quit that program, or start Sniper on another port:
    SNIPER_PORT=3100 install/start.command"
fi
mkdir -p "$LOG_DIR" "$STATE_DIR"
cd "$APP_DIR" || exit 1
PORT="$PORT" nohup node scripts/infra/next_supervisor.mjs start --local >> "$LOG_DIR/app.log" 2>&1 &
echo $! > "$PIDFILE"
say "Starting Project Sniper on http://127.0.0.1:$PORT  (log: $LOG_DIR/app.log)"
for _ in $(seq 1 90); do
  if serving_this_build; then
    say "Ready (build $BUILD_ID). Opening http://127.0.0.1:$PORT"
    [ -n "$SNIPER_NO_OPEN" ] || open "http://127.0.0.1:$PORT"
    exit 0
  fi
  pid_is_our_supervisor "$(cat "$PIDFILE")" || break
  sleep 1
done
fail "The app did not come up serving build $BUILD_ID. The last lines of
  $LOG_DIR/app.log say why; run install/doctor.command as well."

#!/bin/bash
# Project Sniper — start the local app (loopback only) and open it.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
holder="$(port_listener)"
if [ -n "$holder" ]; then
  fail "Port $PORT is already in use by: $holder
  Either quit that program, or start Sniper on another port:
    SNIPER_PORT=3100 \"$PKG_ROOT/install/start.command\""
fi
mkdir -p "$LOG_DIR"
say "Starting Project Sniper on http://127.0.0.1:$PORT"
say "Logs: $LOG_DIR/app.log    Stop it with: install/stop.command"
cd "$APP_DIR" || exit 1
PORT="$PORT" nohup npm run start:local >> "$LOG_DIR/app.log" 2>&1 &
echo $! > "$STATE_DIR/app.pid"
for _ in $(seq 1 60); do
  if curl -fsS -m 2 "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
    say "Ready. Opening http://127.0.0.1:$PORT"
    open "http://127.0.0.1:$PORT"
    exit 0
  fi
  sleep 1
done
fail "The app did not become ready within 60 seconds.
  The last lines of $LOG_DIR/app.log will say why; run install/doctor.command too."

#!/bin/bash
# Project Sniper — check this install and report exactly what is wrong.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
hold_maintenance shared "doctor" "Sniper is being installed, repaired, cleaned or removed right now;
  run the doctor again when that has finished." "$@"
exec "$APP_DIR/.venv/bin/python3" "$PKG_ROOT/install/sniper_doctor.py" "$@"

#!/bin/bash
# Project Sniper — check this install and report exactly what is wrong.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
exec "$APP_DIR/.venv/bin/python3" "$PKG_ROOT/install/sniper_doctor.py" "$@"

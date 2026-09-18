#!/bin/bash
# Project Sniper — write a private-by-construction support bundle to your Desktop.
#   install/diagnostics.command [--include-app-log]
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
exec "$APP_DIR/.venv/bin/python3" "$PKG_ROOT/install/sniper_diagnostics.py" "$@"

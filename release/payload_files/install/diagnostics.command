#!/bin/bash
# Project Sniper — write a private-by-construction support bundle to your Desktop.
#   install/diagnostics.command [--include-app-log]
# Works on a broken or unfinished install too: that is when it is needed.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
[ -f "$ENV_FILE" ] && load_env --moved-ok
PY="$(sniper_python)" || fail "Python 3.12 or newer is required to write the diagnostics bundle."
exec "$PY" "$PKG_ROOT/install/sniper_diagnostics.py" "$@"

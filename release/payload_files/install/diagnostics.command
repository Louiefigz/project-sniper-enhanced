#!/bin/bash
# Project Sniper — write a private-by-construction support bundle to your Desktop.
#   install/diagnostics.command
# Works on a broken or unfinished install too: that is when it is needed.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
[ -f "$ENV_FILE" ] && load_env --moved-ok
PY="$(sniper_python)" || fail "Sniper's own tools are missing, and the diagnostics bundle needs their Python.
  Run install/install.command (it reinstalls them), then run this again."
exec "$PY" "$PKG_ROOT/install/sniper_diagnostics.py" "$@"

#!/usr/bin/env bash
set -euo pipefail
DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export CLAUDE_PROJECT_DIR="$DIR"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || PY="$DIR/.venv/bin/python3"
[ -n "$PY" ] || exit 0
exec "$PY" "$DIR/.claude/hooks/palmier_observer.py"

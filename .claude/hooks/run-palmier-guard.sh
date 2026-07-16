#!/usr/bin/env bash
# PreToolUse wrapper for the Palmier hand-drive guard. Pure-stdlib Python, so it
# just picks an interpreter and forwards the hook event JSON on stdin.
set -euo pipefail
DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export CLAUDE_PROJECT_DIR="$DIR"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || PY="$DIR/.venv/bin/python3"
[ -n "$PY" ] || exit 0
exec "$PY" "$DIR/.claude/hooks/palmier_guard.py"

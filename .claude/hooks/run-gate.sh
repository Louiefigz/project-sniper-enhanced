#!/usr/bin/env bash
# PostToolUse hook wrapper: run the edit_plan gate with the repo venv python
# (fallback: system python3), forwarding the hook event JSON on stdin.
# Fast-path: if the event doesn't even mention edit_plan.json, exit before
# spawning Python — so ordinary code edits pay no cost.
set -euo pipefail
DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export CLAUDE_PROJECT_DIR="$DIR"   # so the Python hook resolves the same repo root
INPUT="$(cat)"
case "$INPUT" in
  *edit_plan.json*) ;;   # possibly a plan write — hand to the gate
  *) exit 0 ;;           # unrelated edit — skip, no Python spawn
esac
PY="$DIR/.venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || exit 0   # no python — can't gate; don't block the edit
printf '%s' "$INPUT" | "$PY" "$DIR/.claude/hooks/edit_plan_gate.py"

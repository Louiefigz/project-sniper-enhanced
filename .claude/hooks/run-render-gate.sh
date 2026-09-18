#!/usr/bin/env bash
# PreToolUse hook wrapper: gate the renderer. Fast-path — if the Bash command
# doesn't invoke assemble.py / render.py, exit before spawning Python so ordinary
# commands pay no cost. Forwards the hook event JSON on stdin.
set -euo pipefail
DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export CLAUDE_PROJECT_DIR="$DIR"   # so the Python hook resolves the same repo root
INPUT="$(cat)"
case "$INPUT" in
  # any render-chain entrypoint that consumes edit_plan.json (SKILL step 6)
  *render.py*|*assemble.py*|*cut_speed.py*|*compile_timeline.py*|*producer.render*|*producer.assemble*|*producer.cut_speed*|*producer.compile_timeline*) ;;
  *) exit 0 ;;                     # unrelated command — allow, no Python spawn
esac
PY="$DIR/.venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || exit 0
printf '%s' "$INPUT" | "$PY" "$DIR/.claude/hooks/render_gate.py"

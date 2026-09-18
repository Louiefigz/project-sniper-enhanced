#!/usr/bin/env python3
"""PostToolUse: bind every Desktop Palmier mutation to fresh readback."""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, TypeError):
        return 0
    tool = str(event.get("tool_name") or "")
    if not tool.startswith("mcp__palmier-pro__"):
        return 0
    repo = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    sys.path.insert(0, os.path.join(repo, "scripts", "producer"))
    try:
        from palmier.desktop_hook import observe_post
        observe_post(event, repo)
    except Exception as exc:
        sys.stderr.write(
            f"PALMIER READBACK FAILED: {tool} — {exc}\n"
            "Do not continue mutating. Run `.venv/bin/python3 scripts/producer/palmier/"
            "desktop_cli.py reconcile` before resuming.\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

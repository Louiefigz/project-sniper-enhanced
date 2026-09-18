#!/usr/bin/env python3
"""PreToolUse: permit only candidate-scoped, staged Palmier mutations.

Read operations remain available for diagnosis. A mutation requires an active
``palmier/desktop_cli.py begin`` lease whose plan, gates, prepared assets,
candidate timeline, and last verified fingerprint all still match. The legacy
``.sniper-palmier-livedrive`` marker and environment bypass are intentionally
ignored: they authorized every mutation without scope or readback.
"""
from __future__ import annotations

import json
import os
import sys


def _producer_path(repo: str) -> None:
    path = os.path.join(repo, "scripts", "producer")
    if path not in sys.path:
        sys.path.insert(0, path)


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, TypeError):
        return 0
    tool = str(event.get("tool_name") or "")
    if not tool.startswith("mcp__palmier-pro__"):
        return 0
    repo = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    _producer_path(repo)
    try:
        from palmier.desktop_hook import authorize_pre
        authorize_pre(event, repo)
    except Exception as exc:
        sys.stderr.write(
            f"BLOCKED: {tool} — {exc}\n\n"
            "Start or resume the governed Desktop candidate with "
            "`.venv/bin/python3 scripts/producer/palmier/desktop_cli.py begin ...`; "
            "read-only Palmier inspection remains available.\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

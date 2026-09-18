#!/usr/bin/env python3
"""PostToolUse gate — the deterministic "teeth" for Claude Code editing.

When Claude writes/edits an ``edit_plan.json`` inside a PRODUCER job, this hook
runs the full deterministic gate set (see gate_lib) and, on any failure, exits 2
with the gate errors on stderr — which Claude Code feeds back as a blocking
message. Claude cannot proceed until it fixes the named errors and writes the
plan again (the gate re-runs automatically). The enforcement is the hook, not
Claude's goodwill — the same teeth the old GUI pipeline had, in code. A plan
written to a manifest-less scratch dir is not gate-able here; the render hook is
the backstop for a plan later moved into a job and rendered.

Contract: PostToolUse event JSON on stdin (``tool_input.file_path`` is the
written file). Exit 0 = pass / not applicable (silent). Exit 2 = block + feed
stderr to Claude.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_lib  # noqa: E402


def main():
    try:
        event = json.loads(sys.stdin.read())
    except Exception:
        return 0  # not our event shape — never block on parse trouble
    plan = (event.get("tool_input") or {}).get("file_path") or ""
    if not plan.endswith("edit_plan.json") or not os.path.isfile(plan):
        return 0
    repo = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    result = gate_lib.evaluate_plan(plan, repo)
    if result is None:
        return 0  # no manifest alongside — not a gate-able producer job
    failures, infra, skipped = result
    if not failures:
        # A gate that couldn't RUN (infra) is not a plan defect — surface it but
        # don't wedge Claude's plan edits over a gate bug. The render hook still
        # fails closed on infra before the irreversible step.
        for gate, errors in infra:
            sys.stderr.write(f"[gate:{gate}] COULD NOT VERIFY — {errors[0] if errors else ''}\n")
        return 0
    sys.stderr.write(gate_lib.format_block(
        failures, infra, skipped,
        "BLOCKED: edit_plan.json failed the deterministic gates. Fix the errors "
        "below, write the plan again (the gate re-runs automatically), and do NOT "
        "render until it passes.") + "\n")
    return 2  # exit 2 → Claude Code blocks and feeds stderr back as the fix list


if __name__ == "__main__":
    sys.exit(main())

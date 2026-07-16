#!/usr/bin/env python3
"""PreToolUse render block — "don't render until the plan passes."

Fires before a Bash command. If the command both (a) names a render-chain
entrypoint that consumes a plan (``render.py``/``assemble.py``/``cut_speed.py``/
``compile_timeline.py`` or their ``-m`` module forms) and (b) carries a resolvable
gate-able ``edit_plan.json``, this hook re-runs the full gate set and exits 2 to
DENY the render on any failure OR any could-not-verify result — the render is
expensive and irreversible, so it fails CLOSED.

Detection is deliberately WRAPPER-AGNOSTIC: it scans all tokens for the renderer
name (so ``caffeinate``/``nice``/``env``/``time``/``mkdir && …`` prefixes and
``&&``/``;`` chains don't hide it), expands ``~``/``$VARS``, honors a leading
``cd``, and looks one level into ``sh -c "…"``. It gates only when a real plan
resolves, so a mere mention (``cat render.py``) or a renderer passed as an
argument is allowed. It CANNOT see through fully opaque forms — a Makefile
target, a shell function/alias, a renamed wrapper script, or a plan path that is
an unexpanded variable or a relative path from a persistent shell cwd. Those are
a documented residual limit; the PostToolUse plan-write gate is the robust
primary control.

Contract: PreToolUse event JSON on stdin (``tool_input.command``). Exit 0 = allow.
Exit 2 = deny + feed stderr to Claude.
"""
import json
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_lib  # noqa: E402

_RENDER_SCRIPTS = ("render.py", "assemble.py", "cut_speed.py", "compile_timeline.py")
_RENDER_MODULES = ("producer.render", "producer.assemble",
                   "producer.cut_speed", "producer.compile_timeline")
_SHELLS = ("sh", "bash", "zsh")


def _expand(token):
    return os.path.expanduser(os.path.expandvars(token))


def _tokens(cmd):
    try:
        return shlex.split(cmd)
    except Exception:
        return cmd.split()


def _strip_cd(tokens, base):
    if len(tokens) >= 3 and tokens[0] == "cd" and tokens[2] in ("&&", ";"):
        target = _expand(tokens[1])
        cwd = target if os.path.isabs(target) else os.path.normpath(os.path.join(base, target))
        return cwd, tokens[3:]
    return base, tokens


def _shell_c_value(tokens):
    if not tokens or os.path.basename(tokens[0]) not in _SHELLS:
        return None
    for i, token in enumerate(tokens):
        if token in ("-c", "-lc") and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def _names_renderer(tokens):
    """True if any token is a render-chain entrypoint — wrapper/chain agnostic."""
    return any(os.path.basename(t) in _RENDER_SCRIPTS
               or any(m in t for m in _RENDER_MODULES) for t in tokens)


def _find_plan(tokens, cwd):
    """A gate-able plan among the args — a ``*.json`` NOT under a ``source/`` dir
    (that's the manifest) whose job has a manifest. Prefers ``edit_plan.json``."""
    candidates = []
    for token in tokens:
        if not token.endswith(".json"):
            continue
        path = _expand(token)
        if not os.path.isabs(path):
            path = os.path.normpath(os.path.join(cwd, path))
        if not os.path.isfile(path) or os.path.basename(os.path.dirname(path)) == "source":
            continue
        if gate_lib.job_paths(path) is not None:
            candidates.append(path)
    candidates.sort(key=lambda p: 0 if os.path.basename(p) == "edit_plan.json" else 1)
    return candidates[0] if candidates else None


def _plan_from_command(cmd, hook_cwd):
    cwd, rest = _strip_cd(_tokens(cmd), hook_cwd)
    inner = _shell_c_value(rest)
    if inner is not None:
        return _plan_from_command(inner, cwd)
    return _find_plan(rest, cwd) if _names_renderer(rest) else None


def main():
    try:
        event = json.loads(sys.stdin.read())
    except Exception:
        return 0
    cmd = (event.get("tool_input") or {}).get("command") or ""
    repo = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    plan = _plan_from_command(cmd, repo)
    if not plan:
        return 0  # not a gate-able render — allow
    result = gate_lib.evaluate_plan(plan, repo)
    if result is None:
        return 0
    failures, infra, skipped = result
    if not failures and not infra:  # render fails CLOSED on infra too
        return 0
    sys.stderr.write(gate_lib.format_block(
        failures, infra, skipped,
        "RENDER BLOCKED: this edit_plan.json has not passed the deterministic "
        "gates. Fix the errors below in the plan, then render again.") + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())

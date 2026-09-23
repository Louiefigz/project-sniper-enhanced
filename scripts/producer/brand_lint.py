#!/usr/bin/env python3
"""brand_lint — the VISUAL-CONSISTENCY gate. Sibling to plan_lint / hook_contract.

Editorial legality already has a gate (plan_lint); this closes the hole that let a
render drift off-style with nothing to stop it. Two modes, both machine-readable,
exit 0 = on-style / exit 1 = rejected:

* **plan**  ``brand_lint.py <edit_plan.json>`` — every ``graphicsTrack`` entry's
  ``kind`` is a registered comp (``templates/motion/compositions/``); a titled
  beat uses a title comp, never a freeform text overlay; any color the plan names
  is a brand token.
* **code**  ``brand_lint.py --scan-code <dir>...`` — no off-token hex color
  literal in pipeline ``.py`` (colors live in ``tokens.css``, not in code). This
  is the check that would have caught my hand-rolled navy ``0x0e1a2b`` + gold.

The style itself is never defined here — it is READ from :mod:`brand` (which reads
``tokens.css`` + the comp catalog), so the gate cannot itself drift.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run-by-path
import brand
from plan_lint import Report  # reuse the errors/warnings + JSON verdict contract

_SKIP_DIRS = ("__pycache__", "tests", ".venv", "node_modules")
_SELF = ("brand.py", "brand_lint.py")  # hold the hex regex, not color literals


def check_graphics(plan: dict, rep: Report) -> None:
    """Every graphic must be an authored comp; every color must be a token."""
    comps = brand.registered_comps()
    tokens = brand.brand_hexes()
    for i, entry in enumerate(plan.get("graphicsTrack") or []):
        kind = entry.get("kind")
        if kind not in comps:
            rep.error(
                f"graphicsTrack[{i}].kind {kind!r} is not a registered comp — a "
                f"select the HyperFrames catalog; use a source-bound native "
                f"project for reference or evidenced custom work")
        for hx in brand.find_hexes(json.dumps(entry.get("spec") or {})):
            if hx not in tokens:
                rep.error(f"graphicsTrack[{i}] color #{hx} is not a brand token "
                          f"(templates/motion/tokens.css)")


def check_title_cards(plan: dict, rep: Report) -> None:
    """Retired title presets cannot pass a standalone brand check."""
    if plan.get("titleCards"):
        rep.error("Legacy titleCards are retired; use a HyperFrames catalog title in the native project")


def _iter_py(paths: list[str]):
    """Yield every pipeline ``.py`` under ``paths`` (skipping tests/caches/self)."""
    for path in paths:
        if os.path.isfile(path) and path.endswith(".py"):
            yield path
            continue
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for name in files:
                if name.endswith(".py") and name not in _SELF:
                    yield os.path.join(root, name)


def scan_code(paths: list[str], rep: Report) -> int:
    """Flag any off-token hex color literal in pipeline code. Returns file count."""
    tokens = brand.brand_hexes()
    scanned = 0
    for fp in _iter_py(paths):
        scanned += 1
        with open(fp, encoding="utf-8", errors="ignore") as f:
            for lineno, line in enumerate(f, 1):
                for hx in brand.find_hexes(line):
                    if hx not in tokens:
                        rep.error(
                            f"{os.path.relpath(fp)}:{lineno} off-token color "
                            f"0x{hx}/#{hx} — colors come from tokens.css, not code")
    return scanned


def lint_plan(plan_path: str, rep: Report) -> None:
    """Run every plan-mode brand check against ``plan_path``."""
    with open(plan_path) as f:
        plan = json.load(f)
    check_graphics(plan, rep)
    check_title_cards(plan, rep)


def main() -> None:
    args = sys.argv[1:]
    rep = Report()
    if args and args[0] == "--scan-code":
        if len(args) < 2:
            print(json.dumps({"error": "Usage: brand_lint.py --scan-code <dir>..."}))
            sys.exit(1)
        n = scan_code(args[1:], rep)
        rep.warn(f"scanned {n} pipeline .py files for off-token colors")
        sys.exit(rep.emit())
    if len(args) != 1:
        print(json.dumps({"error": "Usage: brand_lint.py <edit_plan.json> | "
                                    "--scan-code <dir>..."}))
        sys.exit(1)
    try:
        lint_plan(args[0], rep)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    sys.exit(rep.emit())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Gate a mimic edit plan against a release-ready reference style pack."""
from __future__ import annotations

import argparse
import json
import os
from typing import Any


def _load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _windows(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    grammar = pack.get("grammar") if isinstance(pack.get("grammar"), dict) else {}
    rows = grammar.get("windows") if isinstance(grammar.get("windows"), list) else []
    return {str(row.get("id")): row for row in rows if isinstance(row, dict)}


def _binding_errors(rows: Any, windows: dict[str, dict[str, Any]],
                    lane: str) -> list[str]:
    errors = []
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            errors.append(f"{lane}[{index}] must be an object")
            continue
        grammar_id = row.get("referenceGrammarId")
        window = windows.get(str(grammar_id))
        if window is None:
            errors.append(f"{lane}[{index}] has no valid referenceGrammarId")
            continue
        classification = window.get("classification") or {}
        if lane == "graphicsTrack":
            template = window.get("template") or {}
            if row.get("kind") != template.get("templateId"):
                errors.append(
                    f"{lane}[{index}].kind must match reference template "
                    f"{template.get('templateId')!r}")
            planned_form = row.get("informationForm")
            expected_form = classification.get("informationForm")
            if planned_form != expected_form:
                errors.append(
                    f"{lane}[{index}].informationForm must be {expected_form!r}")
        if lane == "transitions":
            expected = classification.get("transitionFamily")
            if expected in (None, "none"):
                errors.append(f"{lane}[{index}] binds a non-transition grammar window")
            elif row.get("kind") != expected:
                errors.append(f"{lane}[{index}].kind must be {expected!r}")
        if lane == "punchIns":
            expected = classification.get("animationFamily")
            if expected in (None, "none"):
                errors.append(f"{lane}[{index}] binds a non-motion grammar window")
            elif row.get("referenceAnimationFamily") != expected:
                errors.append(
                    f"{lane}[{index}].referenceAnimationFamily must be {expected!r}")
    return errors


def _variety_error(plan: dict[str, Any], pack: dict[str, Any]) -> list[str]:
    rows = plan.get("graphicsTrack") if isinstance(plan.get("graphicsTrack"), list) else []
    grammar = pack.get("grammar") if isinstance(pack.get("grammar"), dict) else {}
    available = {value for value in grammar.get("informationForms") or []
                 if isinstance(value, str)}
    used = {row.get("informationForm") for row in rows if isinstance(row, dict)}
    required = min(3, len(available), len(rows))
    if len(used - {None}) < required:
        return [f"mimic graphics use {len(used - {None})} information forms; "
                f"reference pack supports {len(available)}, require {required}"]
    return []


def lint(plan: dict[str, Any], pack: dict[str, Any], reference_id: str) -> dict[str, Any]:
    """Return a strict style-pack binding verdict."""
    errors = []
    target = plan.get("target") if isinstance(plan.get("target"), dict) else {}
    if pack.get("schemaVersion") != 1 or pack.get("releaseReady") is not True:
        errors.append("reference style pack is not release-ready schema v1")
    if pack.get("referenceId") != reference_id:
        errors.append("reference style pack identity does not match the selected reference")
    if target.get("referenceId") != reference_id:
        errors.append("plan target.referenceId does not match the selected reference")
    if target.get("referenceStrategy") != "mimic":
        errors.append("reference style-pack gate requires target.referenceStrategy='mimic'")
    windows = _windows(pack)
    errors += _binding_errors(plan.get("graphicsTrack"), windows, "graphicsTrack")
    errors += _binding_errors(plan.get("transitions"), windows, "transitions")
    errors += _binding_errors(plan.get("punchIns"), windows, "punchIns")
    errors += _variety_error(plan, pack)
    return {"ok": not errors, "errors": errors,
            "metrics": {"grammarWindows": len(windows),
                        "boundGraphics": len(plan.get("graphicsTrack") or []),
                        "boundTransitions": len(plan.get("transitions") or []),
                        "boundPunches": len(plan.get("punchIns") or [])}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan"); parser.add_argument("style_pack")
    parser.add_argument("--reference-id", required=True)
    args = parser.parse_args()
    try:
        if not os.path.isfile(args.plan) or not os.path.isfile(args.style_pack):
            raise ValueError("plan and style pack must be files")
        verdict = lint(_load(args.plan), _load(args.style_pack), args.reference_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        verdict = {"ok": False, "errors": [str(exc)], "metrics": {}}
    print(json.dumps(verdict))
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

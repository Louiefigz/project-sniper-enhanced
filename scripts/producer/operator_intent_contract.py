#!/usr/bin/env python3
"""Fail closed when a plan drifts from the controller's stored edit intent.

The expected intent is supplied by the controller, not read from ``plan.target``.
This gate checks both identity (mode/scope/lane ownership) and concrete authored
coverage for every unconditional lane. ``auto`` assigns the editorial decision
and deliverable to the system. Every produced/full intro seam needs either a
rendered transition or a time-bound clean-hook receipt proving why a hard cut is
better. A checked transition lane still requires real transition media; a
receipt cannot silently waive a deliverable the operator selected.
Conditional credibility beats remain the content-aware responsibility of
``hook_contract.py``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from edit_scope import (
    LANES, caption_burn_enabled, lane_required, resolve_lanes, resolve_scope,
)
from intro_transition_contract import (
    authored_transition_seams,
    intro_seams,
    valid_clean_hook_receipt,
)
from producer_config import HOOK_CONTRACT_WINDOW_S


_IDENTITY_FIELDS = ("mode", "scope")
_OPTIONAL_TARGET_FIELDS = ("pace", "style", "excerpt", "shortDirection")
_REFERENCE_FIELDS = ("referenceId", "referenceStrategy")
_CREDIBILITY_WORDS = ("credibility", "authority", "receipt", "proof")


def _rows(plan: dict, key: str) -> list:
    value = plan.get(key)
    return value if isinstance(value, list) else []


def _captions_present(plan: dict, mode: str) -> bool:
    from captions.caption_plan_pipeline import validate_plan_caption_authority
    try:
        authority = validate_plan_caption_authority(plan)
    except ValueError:
        return False
    if authority is not None:
        track, _ = authority
        authored = track["defaultPolicy"] != "off" or bool(track["groups"])
        if mode == "short":
            return authored and caption_burn_enabled(plan)
        return authored
    if caption_burn_enabled(plan):
        return True
    if mode == "longform":
        try:
            return lane_required(plan.get("target") or {}, "captions")
        except ValueError:
            return False
    return False


def _check_unsupported_tracks(plan: dict, errors: list[str]) -> None:
    """Reject ghost caption arrays; accept only the render-consumed V1 object."""
    if "captionsTrack" not in plan:
        return
    captions_track = plan.get("captionsTrack")
    if captions_track is None or captions_track == []:
        return
    from captions.caption_plan_pipeline import validate_plan_caption_authority
    try:
        validate_plan_caption_authority(plan)
    except ValueError as exc:
        errors.append(f"captionsTrack is not renderable: {exc}")


def _transitions_present(plan: dict, mode: str) -> bool:
    if not _rows(plan, "transitions"):
        return False
    target = plan.get("target") or {}
    try:
        strict_intro = mode == "longform" and resolve_scope(target) in ("produced", "full")
    except ValueError:
        return False
    if not strict_intro:
        return True
    seams = intro_seams(plan.get("cutTrack") or [], float(HOOK_CONTRACT_WINDOW_S[mode]))
    return bool(authored_transition_seams(plan, seams))


def _credibility_present(plan: dict) -> bool:
    for row in _rows(plan, "graphicsTrack"):
        if not isinstance(row, dict):
            continue
        text = json.dumps(row, sort_keys=True).lower()
        if any(word in text for word in _CREDIBILITY_WORDS):
            return True
    return False


def lane_evidence(plan: dict, mode: str) -> dict[str, bool]:
    """Return concrete, render-addressable evidence for each intent lane."""
    return {
        "motion": bool(_rows(plan, "punchIns")),
        "graphics": bool(_rows(plan, "graphicsTrack")),
        "transitions": _transitions_present(plan, mode),
        "captions": _captions_present(plan, mode),
        "broll": bool(_rows(plan, "brollTrack")),
        "credibility": _credibility_present(plan),
    }


def transition_decision(plan: dict, mode: str | None = None) -> str:
    """Classify the transition lane's deterministic authored-decision receipt."""
    if "transitions" not in plan:
        return "missing"
    transitions = plan.get("transitions")
    if not isinstance(transitions, list):
        return "malformed"
    if transitions:
        return "authored"
    target = plan.get("target") or {}
    actual_mode = mode or target.get("mode")
    try:
        strict = (actual_mode == "longform"
                  and resolve_scope(target) in ("produced", "full"))
    except ValueError:
        strict = True
    if not strict:
        return "explicitly-empty"
    hook_s = float(HOOK_CONTRACT_WINDOW_S.get(actual_mode, 60.0))
    seams = intro_seams(plan.get("cutTrack") or [], hook_s)
    return "clean-hook" if valid_clean_hook_receipt(plan, seams) else "unjustified-empty"


def lane_coverage(plan: dict, mode: str) -> tuple[dict[str, bool], dict[str, bool]]:
    """Return render evidence and discharged system-owned lane obligations."""
    evidence = lane_evidence(plan, mode)
    coverage = dict(evidence)
    # The UI labels automatic lanes as required. A clean-hook receipt is a
    # per-seam editorial decision, not the transition deliverable itself.
    coverage["transitions"] = evidence["transitions"] or (
        transition_decision(plan, mode) == "explicitly-empty"
    )
    return evidence, coverage


def _validate_expected(expected: Any) -> dict:
    if not isinstance(expected, dict):
        raise ValueError("expected operator intent must be an object")
    if expected.get("mode") not in ("short", "longform"):
        raise ValueError("expected operator intent has no valid mode")
    if "scope" not in expected:
        raise ValueError("expected operator intent has no scope")
    if not isinstance(expected.get("lanes", {}), dict):
        raise ValueError("expected operator intent lanes must be an object")
    resolve_lanes(expected)
    return expected


def _check_identity(plan: dict, expected: dict, errors: list[str]) -> dict:
    target = plan.get("target")
    if not isinstance(target, dict):
        errors.append("plan.target is missing; operator intent cannot be verified")
        return {}
    for field in _IDENTITY_FIELDS:
        if target.get(field) != expected.get(field):
            errors.append(
                f"target.{field} {target.get(field)!r} does not match stored "
                f"operator intent {expected.get(field)!r}"
            )
    for field in _OPTIONAL_TARGET_FIELDS:
        if field in expected and target.get(field) != expected[field]:
            errors.append(f"target.{field} does not match stored operator intent")
    return target


def _check_reference(target: dict, expected: dict, errors: list[str]) -> None:
    reference = expected.get("reference")
    wanted = {
        "referenceId": reference.get("id") if isinstance(reference, dict) else None,
        "referenceStrategy": reference.get("strategy") if isinstance(reference, dict) else None,
    }
    for field in _REFERENCE_FIELDS:
        actual = target.get(field)
        if actual != wanted[field]:
            errors.append(f"target.{field} {actual!r} does not match stored operator intent {wanted[field]!r}")


def _resolved_lanes(target: dict, expected: dict, errors: list[str]) -> tuple[dict, dict]:
    try:
        actual = resolve_lanes(target)
    except ValueError as error:
        errors.append(f"plan target lanes are invalid: {error}")
        actual = {}
    wanted = resolve_lanes(expected)
    for lane in LANES:
        if actual.get(lane) != wanted[lane]:
            errors.append(
                f"lane {lane!r} resolves to {actual.get(lane)!r}; stored operator "
                f"intent requires {wanted[lane]!r}"
            )
    return actual, wanted


def _check_coverage(plan: dict, wanted: dict, mode: str,
                    errors: list[str]) -> tuple[dict[str, bool], dict[str, bool]]:
    evidence, coverage = lane_coverage(plan, mode)
    for lane in LANES:
        state = wanted[lane]
        present = evidence[lane]
        if lane == "credibility" and state == "auto":
            continue  # content-gated by hook_contract.py
        if state == "auto" and not coverage[lane]:
            errors.append(f"lane {lane!r} is assigned to Auto Edit but the plan authors no {lane} coverage")
        if state != "auto" and present:
            errors.append(f"lane {lane!r} is {state!r} in operator intent but the plan authors that lane")
    return evidence, coverage


def _check_finish(plan: dict, expected: dict, errors: list[str]) -> None:
    music = plan.get("music") if isinstance(plan.get("music"), dict) else {}
    if music.get("enabled", False) is not expected.get("music", False):
        errors.append("plan.music.enabled does not match stored operator intent")
    if plan.get("audioEnhance") != expected.get("audioEnhance"):
        errors.append("plan.audioEnhance does not match stored operator intent")


def evaluate(plan: dict, raw_expected: Any) -> dict:
    """Return the planning-gate JSON verdict for one plan and expected intent."""
    errors: list[str] = []
    try:
        expected = _validate_expected(raw_expected)
    except ValueError as error:
        return {"ok": False, "errors": [str(error)], "warnings": [], "metrics": {}}
    _check_unsupported_tracks(plan, errors)
    target = _check_identity(plan, expected, errors)
    _check_reference(target, expected, errors)
    _actual, wanted = _resolved_lanes(target, expected, errors)
    evidence, coverage = _check_coverage(plan, wanted, expected["mode"], errors)
    _check_finish(plan, expected, errors)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": [],
        "scope": expected["scope"],
        "metrics": {
            "laneCoverage": coverage,
            "laneEvidence": evidence,
            "transitionDecision": transition_decision(plan, expected["mode"]),
            "credibility": "content-gated",
        },
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan")
    parser.add_argument("--expected-json", required=True)
    args = parser.parse_args()
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        expected = json.loads(args.expected_json)
        verdict = evaluate(plan, expected)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        verdict = {"ok": False, "errors": [f"operator intent gate failed: {error}"], "warnings": []}
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_cli())

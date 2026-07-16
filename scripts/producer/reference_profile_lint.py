#!/usr/bin/env python3
"""Gate an edit plan against one server-resolved reference style profile.

Identity, requested mode, and strategy are hard contracts. Measured mechanics
normally produce deterministic warnings; a ``mimic`` plan also fails when a
material rate differs by more than 5x (or adds >=4/min where the reference has
none). Missing profile metrics remain tolerated.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any


STRATEGIES = ("mimic", "extend", "new-style")
RATE_KEYS = ("cuts", "graphics", "punches", "transitions")
TOLERANCE = {"mimic": 0.35, "extend": 0.50, "new-style": 0.50}
MIMIC_HARD_RATIO = (0.20, 5.0)
MIMIC_HARD_DELTA_PER_MIN = 4.0


@dataclass(frozen=True)
class Expected:
    """Route-owned identity that neither the plan nor profile may redefine."""

    reference_id: str
    mode: str
    strategy: str
    target_style: str | None = None


def load_object(path: str) -> dict[str, Any]:
    """Load one required JSON object."""
    if not os.path.isfile(path):
        raise ValueError(f"not a file: {path}")
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def number(value: Any) -> float | None:
    """Finite non-negative number, excluding bool; otherwise None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if 0.0 <= numeric < float("inf") else None


def output_duration(plan: dict[str, Any]) -> float | None:
    """Compiled-duration estimate from cutTrack, then target fallback."""
    total = 0.0
    rows = plan.get("cutTrack")
    if isinstance(rows, list) and rows:
        for row in rows:
            if not isinstance(row, dict):
                return None
            start, end = number(row.get("start")), number(row.get("end"))
            speed = number(row.get("speed", 1.0))
            if start is None or end is None or speed is None or speed <= 0 or end <= start:
                return None
            total += (end - start) / speed
        return total
    target = plan.get("target") if isinstance(plan.get("target"), dict) else {}
    return number(target.get("durationTargetS"))


def rate(count: int, duration_s: float | None) -> float | None:
    """Count per minute when duration is usable."""
    if duration_s is None or duration_s <= 0:
        return None
    return round(count * 60.0 / duration_s, 3)


def plan_rates(plan: dict[str, Any]) -> tuple[dict[str, float | None], float | None]:
    """Comparable plan event rates in output time."""
    duration = output_duration(plan)
    cuts = plan.get("cutTrack") if isinstance(plan.get("cutTrack"), list) else []
    graphics = plan.get("graphicsTrack") if isinstance(plan.get("graphicsTrack"), list) else []
    titles = plan.get("titleCards") if isinstance(plan.get("titleCards"), list) else []
    punches = plan.get("punchIns") if isinstance(plan.get("punchIns"), list) else []
    transitions = plan.get("transitions") if isinstance(plan.get("transitions"), list) else []
    counts = {
        "cuts": max(0, len(cuts) - 1),
        "graphics": len(graphics) + len(titles),
        "punches": len(punches),
        "transitions": len(transitions),
    }
    return {key: rate(value, duration) for key, value in counts.items()}, duration


def first_metric(metrics: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    """First numeric metric among compatible aliases."""
    for key in keys:
        value = number(metrics.get(key))
        if value is not None:
            return value
    return None


def component_rate(metrics: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    """Sum present component rates; return None when none exist."""
    values = [number(metrics.get(key)) for key in keys]
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def coalesce(*values: float | None) -> float | None:
    """First present rate, preserving a measured zero."""
    return next((value for value in values if value is not None), None)


def transition_class_rate(profile: dict[str, Any], mechanics: dict[str, Any]) -> float | None:
    """Non-hard seam classes per minute when no explicit transition rate exists."""
    classes = mechanics.get("transitionClasses")
    source = profile.get("source") if isinstance(profile.get("source"), dict) else {}
    duration = first_metric(source, ("durationS", "duration"))
    if not isinstance(classes, dict) or duration is None:
        return None
    count = sum(
        value for key, raw in classes.items()
        if key in {"sweep", "fade", "flash"} and (value := number(raw)) is not None
    )
    return rate(round(count), duration)


def profile_rates(profile: dict[str, Any]) -> dict[str, float | None]:
    """Normalize the profile's optional mechanics metrics."""
    mechanics = profile.get("mechanics") if isinstance(profile.get("mechanics"), dict) else {}
    events = mechanics.get("eventRatesPerMin")
    events = events if isinstance(events, dict) else {}
    explicit_transition = first_metric(events, ("transitions", "transition"))
    return {
        "cuts": coalesce(first_metric(mechanics, ("cutsPerMin",)),
                         first_metric(events, ("cuts", "cut"))),
        "graphics": coalesce(first_metric(events, ("graphics", "graphic")),
                             component_rate(events, ("graphic-in", "panel-in"))),
        "punches": coalesce(first_metric(events, ("punches", "punch")),
                            component_rate(events, ("zoom-in", "zoom-out"))),
        "transitions": explicit_transition
        if explicit_transition is not None else transition_class_rate(profile, mechanics),
    }


def identity_errors(plan: dict[str, Any], profile: dict[str, Any], expected: Expected) -> list[str]:
    """Hard provenance and format contract."""
    target = plan.get("target") if isinstance(plan.get("target"), dict) else {}
    checks = (
        ("profile.referenceId", profile.get("referenceId"), expected.reference_id),
        ("target.referenceId", target.get("referenceId"), expected.reference_id),
        ("target.referenceStrategy", target.get("referenceStrategy"), expected.strategy),
        ("target.mode", target.get("mode"), expected.mode),
    )
    errors = [f"{label} must be {want!r}, got {got!r}" for label, got, want in checks if got != want]
    actual_style = target.get("style")
    wanted_style = expected.target_style if expected.strategy == "extend" else None
    if actual_style != wanted_style:
        errors.append(f"target.style must be {wanted_style!r} for strategy {expected.strategy!r}, got {actual_style!r}")
    if expected.strategy == "extend" and target.get("pace") != expected.target_style:
        errors.append(
            f"target.pace must be {expected.target_style!r} for strategy 'extend', "
            f"got {target.get('pace')!r}"
        )
    return errors


def mode_suggestion_warning(profile: dict[str, Any], expected: Expected) -> list[str]:
    """A machine-suggested mode never overrides the operator-confirmed mode."""
    suggested = profile.get("suggestedMode")
    if suggested in ("short", "longform") and suggested != expected.mode:
        return [
            f"profile suggested mode {suggested!r}; operator-confirmed mode "
            f"{expected.mode!r} remains authoritative"
        ]
    return []


def rate_warnings(plan: dict[str, float | None], reference: dict[str, float | None],
                  strategy: str) -> list[str]:
    """Warn on available rate deltas; never fail creative variance."""
    warnings: list[str] = []
    tolerance = TOLERANCE[strategy]
    for key in RATE_KEYS:
        actual, expected = plan.get(key), reference.get(key)
        if actual is None or expected is None:
            continue
        low, high = expected * (1.0 - tolerance), expected * (1.0 + tolerance)
        outside = actual > 0 if expected == 0 else actual < low or actual > high
        if outside:
            warnings.append(
                f"reference rate {key}: plan {actual:.2f}/min vs profile {expected:.2f}/min "
                f"(strategy {strategy}, expected {low:.2f}-{high:.2f}/min)"
            )
    return warnings


def mimic_rate_errors(plan: dict[str, float | None], reference: dict[str, float | None]) -> list[str]:
    """Reject only severe, material divergence for a literal mimic request."""
    errors: list[str] = []
    low_ratio, high_ratio = MIMIC_HARD_RATIO
    for key in RATE_KEYS:
        actual, expected = plan.get(key), reference.get(key)
        if key == "graphics" and actual is not None and expected is not None:
            if (expected >= 8.0 and actual < 2.0) or (expected <= 1.0 and actual >= 8.0):
                errors.append(
                    f"mimic rate graphics: plan {actual:.2f}/min omits or invents a "
                    f"material graphics system (profile {expected:.2f}/min)"
                )
            continue
        if actual is None or expected is None or abs(actual - expected) < MIMIC_HARD_DELTA_PER_MIN:
            continue
        outside = actual >= MIMIC_HARD_DELTA_PER_MIN if expected == 0 else not (
            expected * low_ratio <= actual <= expected * high_ratio
        )
        if outside:
            errors.append(
                f"mimic rate {key}: plan {actual:.2f}/min is materially outside "
                f"profile {expected:.2f}/min"
            )
    return errors


def lint(plan: dict[str, Any], profile: dict[str, Any], expected: Expected) -> dict[str, Any]:
    """Return the machine-readable route verdict."""
    actual, duration = plan_rates(plan)
    reference = profile_rates(profile)
    errors = identity_errors(plan, profile, expected)
    if expected.strategy == "mimic":
        errors += mimic_rate_errors(actual, reference)
    warnings = mode_suggestion_warning(profile, expected)
    warnings += rate_warnings(actual, reference, expected.strategy)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "durationS": round(duration, 3) if duration is not None else None,
            "planRatesPerMin": actual,
            "referenceRatesPerMin": reference,
        },
    }


def parse_args() -> argparse.Namespace:
    """CLI contract used by the authoring prompt and route-side gate."""
    parser = argparse.ArgumentParser(description="Lint an edit plan against a reference profile")
    parser.add_argument("plan")
    parser.add_argument("profile")
    parser.add_argument("--reference-id", required=True)
    parser.add_argument("--mode", required=True, choices=("short", "longform"))
    parser.add_argument("--strategy", required=True, choices=STRATEGIES)
    parser.add_argument("--target-style", choices=("caleb", "jadenly", "angela"))
    return parser.parse_args()


def main() -> int:
    """Load, lint, print one JSON verdict, and use exit 1 only for hard errors."""
    args = parse_args()
    try:
        if args.strategy == "extend" and not args.target_style:
            raise ValueError("--target-style is required for strategy extend")
        if args.strategy != "extend" and args.target_style:
            raise ValueError("--target-style is valid only for strategy extend")
        expected = Expected(args.reference_id, args.mode, args.strategy, args.target_style)
        verdict = lint(load_object(args.plan), load_object(args.profile), expected)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        verdict = {"ok": False, "errors": [str(exc)], "warnings": [], "metrics": {}}
    print(json.dumps(verdict))
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

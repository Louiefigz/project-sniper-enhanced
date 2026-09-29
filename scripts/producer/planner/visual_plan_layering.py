"""Explicit concurrent visual windows without relaxing density or repeat caps."""
from __future__ import annotations

from planner.visual_plan_fields import (
    VisualPlanContractError, id_field, object_field, strings_field, text_field,
)

VisualWindow = tuple[str, int, int]


def validate_layering(opportunities: list[dict]) -> None:
    """Validate bounded, reasoned relationships between overlapping windows."""
    by_id = {row["id"]: row for row in opportunities}
    for opportunity in opportunities:
        if "layering" not in opportunity:
            continue
        _validate_layering_record(opportunity, by_id)


def _validate_layering_record(opportunity: dict, by_id: dict[str, dict]) -> None:
    name = f"opportunity {opportunity['id']} layering"
    layering = object_field(opportunity["layering"], name,
                            {"withOpportunityIds", "reason"}, set())
    text_field(layering["reason"], f"{name} reason")
    targets = strings_field(layering["withOpportunityIds"], f"{name} targets", 8)
    if not targets:
        raise VisualPlanContractError(f"{name} needs at least one target")
    for target in targets:
        id_field(target, f"{name} target")
        other = by_id.get(target)
        if other is None or target == opportunity["id"]:
            raise VisualPlanContractError(f"{name} target is unknown or self")
        if not _overlaps(opportunity["timing"], other["timing"]):
            raise VisualPlanContractError(f"{name} target must overlap its window")


def _overlaps(left: dict, right: dict) -> bool:
    return (left["startFrame"] < right["endFrameExclusive"]
            and right["startFrame"] < left["endFrameExclusive"])


def breathing_conflict(plan: dict, opportunity: dict,
                       windows: tuple[VisualWindow, ...]) -> bool:
    """Keep breathing room except for explicitly declared concurrent pairs."""
    start = opportunity["timing"]["startFrame"]
    breathing = plan["direction"]["density"]["minBreathingFrames"]
    by_id = {row["id"]: row for row in plan["opportunities"]}
    for prior_id, _, prior_end in windows:
        if start >= prior_end + breathing:
            continue
        prior = by_id[prior_id]
        if start < prior_end and _declared_pair(opportunity, prior):
            continue
        return True
    return False


def _declared_pair(left: dict, right: dict) -> bool:
    left_targets = left.get("layering", {}).get("withOpportunityIds", [])
    right_targets = right.get("layering", {}).get("withOpportunityIds", [])
    return right["id"] in left_targets or left["id"] in right_targets


def advance_visual_windows(plan: dict, opportunity: dict,
                           windows: tuple[VisualWindow, ...]) -> tuple[VisualWindow, ...]:
    """Retain every still-relevant visual, including long underlying layers."""
    timing = opportunity["timing"]
    breathing = plan["direction"]["density"]["minBreathingFrames"]
    active = tuple(row for row in windows
                   if timing["startFrame"] < row[2] + breathing)
    return active + ((opportunity["id"], timing["startFrame"],
                      timing["endFrameExclusive"]),)

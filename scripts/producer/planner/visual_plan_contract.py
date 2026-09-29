"""Public validation and fingerprint API for VISUAL-PLAN.json."""
from __future__ import annotations

import copy

from planner.visual_plan_fields import (
    VisualPlanContractError,
    canonical_hash,
    id_field,
    object_field,
)
from planner.visual_plan_validation import validate_plan_structure

__all__ = [
    "VisualPlanContractError",
    "canonical_hash",
    "invalidation_inputs",
    "validate_visual_plan",
]


def validate_visual_plan(value: object,
                         receipt_authority: dict | None = None) -> dict:
    """Validate planning bounds, source pins, opportunities, and allocation."""
    required = {"schemaVersion", "scope", "planId", "project", "catalogPin",
                "transcriptAuthority", "mediaAuthority", "relatedUsageAuthority",
                "searchAuthority",
                "direction", "bounds",
                "relatedUsage", "opportunities", "allocation"}
    plan = object_field(value, "visual plan", required, set())
    if plan["schemaVersion"] != 1:
        raise VisualPlanContractError("visual plan version is unsupported")
    if plan["scope"] != "visual-plan-planning-evidence":
        raise VisualPlanContractError("visual plan scope is unsupported")
    id_field(plan["planId"], "planId")
    validate_plan_structure(plan, receipt_authority)
    canonical_hash(plan)
    return copy.deepcopy(plan)


def invalidation_inputs(value: object,
                        receipt_authority: dict | None = None) -> dict:
    """Separate visual invalidation from reusable source/audio authority."""
    plan = validate_visual_plan(value, receipt_authority)
    upstream = {key: plan["project"][key] for key in (
        "intentSha256", "acceptedProgramSha256", "transcriptSha256")}
    project_visual = {key: plan["project"][key] for key in (
        "mode", "aspect", "durationFrames", "fps")}
    picture = {key: plan[key] for key in (
        "catalogPin", "mediaAuthority", "searchAuthority", "direction", "relatedUsage",
        "opportunities", "allocation")}
    picture["project"] = project_visual
    return {
        "visualPlanSha256": canonical_hash(plan),
        "pictureInputSha256": canonical_hash(picture),
        "catalogPinSha256": canonical_hash(plan["catalogPin"]),
        "upstreamAuthoritySha256": canonical_hash(upstream),
    }

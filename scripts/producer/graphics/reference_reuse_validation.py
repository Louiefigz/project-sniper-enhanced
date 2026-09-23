"""Validate authored reuse decisions independently of catalog discovery.

Descriptions are attributed agent assessments. Completeness is machine-checkable;
whether a picture actually matches the reference still needs visual review.
"""
from __future__ import annotations

from graphics.reference_reuse_map import require, text_field

ROUTES = {"reuse", "configure", "compose", "custom", "blocked"}
GAP_TYPES = {"missing-capability", "quality-failure"}
PREREQUISITES = {"source", "asset", "adapter", "other"}


def _prerequisites(value: object) -> list[dict]:
    """Keep absent resources and execution adapters distinct from capability gaps."""
    require(isinstance(value, list), "prerequisites must be a list")
    for item in value:
        require(isinstance(item, dict) and isinstance(item.get("kind"), str)
                and item["kind"] in PREREQUISITES,
                "invalid prerequisite kind")
        text_field(item.get("detail"), "prerequisite detail")
    return value


def _inspection(row: dict, candidates: dict) -> None:
    """Bind an agent's inspection to exact candidate and source bytes."""
    candidate = candidates[row["ref"]]
    require(row.get("candidateSha256") == candidate["sha256"], "inspection candidate changed")
    require(candidate["source"]["exists"], "missing source is a prerequisite, not an inspected gap")
    text_field(row.get("observation"), "inspection observation")
    fit = row.get("fit")
    require(fit in ("usable", "gap", "prerequisite"), "inspection fit must be explicit")
    prerequisites = _prerequisites(row.get("prerequisites", []))
    require(not prerequisites or fit == "prerequisite", "unresolved resources must remain prerequisites")
    if fit == "gap":
        require(isinstance(row.get("gapType"), str) and row["gapType"] in GAP_TYPES,
                "gap needs a capability or quality classification")
        text_field(row.get("limitations"), "inspected capability/quality limitation")
    if fit == "prerequisite":
        require(prerequisites, "prerequisite inspection needs a concrete blocker")
    if fit != "gap":
        require(row.get("gapType") is None, "prerequisites are not capability gaps")


def _inspections(shot: dict, candidates: dict) -> dict[str, dict]:
    """Require unique exact candidates from this shot's frozen search scope."""
    rows = shot.get("inspections")
    require(isinstance(rows, list), "shot inspections must be a list")
    result = {}
    for row in rows:
        require(isinstance(row, dict), "inspection must be an object")
        ref = row.get("ref")
        require(isinstance(ref, str) and ref in shot["candidateRefs"], "unknown inspection ref")
        require(ref not in result, "duplicate inspection ref")
        _inspection(row, candidates)
        result[ref] = row
    return result


def _pieces(decision: dict, inspections: dict) -> list[dict]:
    """Retain usable inspected components with their planned adaptation."""
    pieces = decision.get("pieces")
    require(isinstance(pieces, list), "decision pieces must be a list")
    seen = set()
    for piece in pieces:
        require(isinstance(piece, dict), "selected piece must be an object")
        ref = piece.get("ref")
        require(isinstance(ref, str) and ref in inspections, "selected ref was not inspected")
        require(ref not in seen, "duplicate selected ref")
        fit = inspections[ref]["fit"]
        require(fit == "usable" or (fit == "gap" and decision["route"] == "custom"),
                "selected piece has an unresolved gap/prerequisite")
        text_field(piece.get("role"), "selected piece role")
        require(isinstance(piece.get("changes"), str), "piece changes must be explicit text")
        if fit == "gap":
            text_field(piece["changes"], "partial reuse changes")
        seen.add(ref)
    return pieces


def _execution(decision: dict, prerequisites: list[dict]) -> None:
    """Record adapter readiness without inferring it from legacy catalog status."""
    execution = decision.get("execution")
    require(isinstance(execution, dict), "execution adapter assessment required")
    text_field(execution.get("adapter"), "execution adapter")
    status = execution.get("status")
    require(status in ("available", "unavailable", "unverified"), "invalid execution adapter status")
    if status != "available":
        require(decision["route"] == "blocked", "unavailable/unverified adapter is a blocker")
        require(any(row["kind"] == "adapter" for row in prerequisites),
                "unavailable/unverified adapter needs an adapter prerequisite")


def _custom(custom: object, inspections: dict, pieces: list[dict]) -> None:
    """Require an inspected capability/quality gap and a bounded custom addition."""
    require(isinstance(custom, dict), "custom route requires a gap comparison")
    require(isinstance(custom.get("gapType"), str) and custom["gapType"] in GAP_TYPES,
            "custom needs capability/quality gapType")
    for field in ("gap", "scope", "retainedPiecesRationale"):
        text_field(custom.get(field), f"custom {field}")
    closest = custom.get("closest")
    require(isinstance(closest, list) and closest, "search miss alone does not justify custom")
    seen = set()
    for comparison in closest:
        require(isinstance(comparison, dict), "closest comparison must be an object")
        ref = comparison.get("ref")
        require(isinstance(ref, str) and ref in inspections, "closest option was not inspected")
        require(ref not in seen, "duplicate closest comparison")
        require(inspections[ref]["fit"] == "gap", "closest option must have an inspected gap")
        require(inspections[ref]["gapType"] == custom["gapType"], "closest gap classification differs")
        text_field(comparison.get("reason"), "closest option comparison")
        seen.add(ref)
    require(custom.get("retainedRefs") == [piece["ref"] for piece in pieces],
            "custom retainedRefs must preserve the selected reusable pieces")
    require(all(inspections[piece["ref"]]["fit"] != "gap" or piece["ref"] in seen
                for piece in pieces), "selected partial reuse gap was not compared")


def _decision(shot: dict, candidates: dict) -> bool:
    """Validate one route without imposing reference matching on other work."""
    inspections = _inspections(shot, candidates)
    decision = shot.get("decision")
    require(isinstance(decision, dict) and isinstance(decision.get("route"), str)
            and decision["route"] in ROUTES,
            "shot decision is pending or invalid")
    route = decision["route"]
    text_field(decision.get("reason"), "decision reason")
    prerequisites = _prerequisites(decision.get("prerequisites"))
    _execution(decision, prerequisites)
    pieces = _pieces(decision, inspections)
    require(bool(prerequisites) == (route == "blocked"), "unresolved prerequisites require blocked route")
    if route in ("reuse", "configure"):
        require(len(pieces) == 1, "reuse/configure requires exactly one inspected piece")
        changed = bool(pieces[0]["changes"].strip())
        require(changed == (route == "configure"), "configure needs changes; reuse has none")
    if route == "compose":
        require(len(pieces) >= 2, "compose requires at least two inspected pieces")
    if route == "custom":
        _custom(decision.get("custom"), inspections, pieces)
    else:
        require(decision.get("custom") is None, "custom justification belongs only to custom route")
    return route == "blocked"


def validate_decisions(shots: list[dict], candidates: dict) -> list[str]:
    """Return explicitly blocked shot IDs after every decision is complete."""
    return [shot["id"] for shot in shots if _decision(shot, candidates)]

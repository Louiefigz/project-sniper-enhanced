"""Stable-ID plan differ for incremental Desktop Palmier revisions."""
from __future__ import annotations

from dataclasses import dataclass

from fingerprints import json_canon, plan_content_hash
from palmier.mcp_client import PalmierError
from palmier.revision_dependencies import DependencyInput, dependency_closure
from palmier.revision_schema import validate_revision

IGNORED_LANES = {"planVersion", "graphicsDecisions"}
PIXEL_METADATA = {"id", "semanticBeatId", "outStart", "outEnd", "reason"}


@dataclass(frozen=True)
class RevisionDiffInput:
    """Inputs required to derive one candidate-bound revision set."""

    old_plan: dict
    new_plan: dict
    ledger: dict
    candidate_fingerprint: str


def _same(left: object, right: object) -> bool:
    return json_canon(left) == json_canon(right)


def _graphics(plan: dict) -> dict[str, dict]:
    rows = plan.get("graphicsTrack") or []
    if not isinstance(rows, list):
        raise PalmierError("graphicsTrack must be a list for revision planning")
    result: dict[str, dict] = {}
    for index, row in enumerate(rows):
        ident = row.get("id") if isinstance(row, dict) else None
        if not isinstance(ident, str) or not ident:
            raise PalmierError(f"graphicsTrack[{index}] needs a stable id")
        if ident in result:
            raise PalmierError(f"duplicate graphicsTrack id {ident!r}")
        result[ident] = row
    return result


def _version(ledger: dict, ident: str) -> int:
    elements = ledger.get("elements") if isinstance(ledger, dict) else None
    row = elements.get(ident) if isinstance(elements, dict) else None
    value = row.get("version", 1) if isinstance(row, dict) else 0
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _pixel_payload(row: dict) -> dict:
    return {key: value for key, value in row.items() if key not in PIXEL_METADATA}


def _duration(row: dict) -> float:
    return float(row.get("outEnd", 0)) - float(row.get("outStart", 0))


def _operation(payload: dict) -> dict:
    return {"lane": "graphics", **payload}


def _changed_graphics(context: RevisionDiffInput) -> list[dict]:
    before, after = _graphics(context.old_plan), _graphics(context.new_plan)
    result: list[dict] = []
    for ident in sorted(set(before) | set(after)):
        old, new = before.get(ident), after.get(ident)
        version = _version(context.ledger, ident)
        payload = {"elementId": ident, "expectedVersion": version,
                   "before": old, "after": new,
                   "sourceAnchor": (new or old or {}).get("semanticBeatId")}
        if old is None:
            result.append(_operation({**payload, "action": "add"}))
        elif new is None:
            result.append(_operation({**payload, "action": "remove"}))
        elif _same(old, new):
            continue
        elif _same(_pixel_payload(old), _pixel_payload(new)) \
                and abs(_duration(old) - _duration(new)) < 1e-6:
            result.append(_operation({**payload, "action": "move"}))
        else:
            result.append(_operation({**payload, "action": "replace"}))
    return result


def _changed_lanes(old: dict, new: dict) -> list[str]:
    keys = set(old) | set(new)
    return sorted(key for key in keys if not key.startswith("_")
                  and key not in IGNORED_LANES
                  and not _same(old.get(key), new.get(key)))


def _duration_s(plan: dict) -> float:
    return sum((float(row["end"]) - float(row["start"]))
               / float(row.get("speed", 1.0) or 1.0)
               for row in plan.get("cutTrack") or [])


def build_revision(context: RevisionDiffInput) -> dict:
    """Derive a deterministic revision set and its invalidation closure."""
    operations = _changed_graphics(context)
    changed = _changed_lanes(context.old_plan, context.new_plan)
    unsupported = [lane for lane in changed if lane != "graphicsTrack"]
    closure = dependency_closure(DependencyInput(
        operations, changed, _duration_s(context.new_plan)))
    if unsupported or closure["requiresFullRebuild"]:
        reason = closure.get("reason") or "unsupported plan lanes changed"
        lanes = ", ".join(unsupported or closure["changedLanes"])
        raise PalmierError(
            f"incremental Palmier revision requires a broader rebuild: {reason} ({lanes})")
    if not operations:
        raise PalmierError("incremental Palmier revision found no element changes")
    return validate_revision({
        "basePlanHash": plan_content_hash(context.old_plan),
        "nextPlanHash": plan_content_hash(context.new_plan),
        "baseCandidateFingerprint": context.candidate_fingerprint,
        "operations": operations, "dependencies": closure,
    })

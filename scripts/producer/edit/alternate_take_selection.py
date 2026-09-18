"""Closed deterministic selection policy for alternate-take candidates."""
from __future__ import annotations

from dataclasses import dataclass

from edit.alternate_take_types import AlternateTakeAuthorityError


@dataclass(frozen=True)
class AlternateTakeDecision:
    """Explicit caller decision checked against the released controller policy."""

    selected_candidate_id: str
    selection_policy: dict
    visual_speech_region: dict


def released_selection_policy() -> dict:
    """Return the only policy permitted to auto-select an alternate take."""
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-alternate-take-selection-policy",
        "strategy": "deterministic-retake-scan-later-take",
        "ambiguityDisposition": "block",
        "operatorRequiredDisposition": "block",
    }


def _region(value: object) -> dict:
    keys = {"xPpm", "yPpm", "widthPpm", "heightPpm"}
    if not isinstance(value, dict) or set(value) != keys \
            or any(type(value[key]) is not int for key in keys):
        raise AlternateTakeAuthorityError(
            "visual speech region is malformed")
    x, y = value["xPpm"], value["yPpm"]
    width, height = value["widthPpm"], value["heightPpm"]
    if min(x, y) < 0 or min(width, height) <= 0 \
            or x + width > 1_000_000 or y + height > 1_000_000:
        raise AlternateTakeAuthorityError(
            "visual speech region escapes the normalized frame")
    return dict(value)


def select_candidate(
    candidate_set: dict,
    decision: AlternateTakeDecision,
) -> tuple[dict, dict]:
    """Resolve the unique later take or block ambiguity/policy drift."""
    policy = released_selection_policy()
    if decision.selection_policy != policy:
        raise AlternateTakeAuthorityError(
            "alternate-take selection policy is not released")
    rows = candidate_set.get("candidates")
    if not isinstance(rows, list):
        raise AlternateTakeAuthorityError(
            "alternate-take candidates are absent")
    identifiers = [row.get("candidateId") for row in rows
                   if isinstance(row, dict)]
    later = [row for row in rows
             if isinstance(row, dict) and row.get("role") == "later"]
    if len(rows) != len(identifiers) or len(set(identifiers)) != len(rows) \
            or len(later) != 1:
        raise AlternateTakeAuthorityError(
            "alternate-take selection is ambiguous")
    selected = later[0]
    if decision.selected_candidate_id != selected.get("candidateId"):
        raise AlternateTakeAuthorityError(
            "explicit alternate-take selection violates released policy")
    return selected, _region(decision.visual_speech_region)

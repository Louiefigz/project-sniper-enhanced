"""Deterministic maximum-distinct assignment for semantic graphic forms."""
from __future__ import annotations

from collections import Counter
from typing import Mapping

from graphics.comp_capabilities import is_aspect_legal_kind
from graphics.visual_source_policy import integrated_kinds

# These forms are registered templates but cannot survive the deterministic
# render gates yet.  Keep this capability boundary beside allocation so both
# semantic discovery and matching use the same executable set.
GATE_ILLEGAL_KINDS = frozenset({"canvas-pip-list"})

# The semantic-allocation lane is the LONGFORM intro machine: semantic_beats
# emits "source-derived compatible 16:9 forms" and nothing else feeds this
# allocator, so a kind the measured matrix pins to a 9:16 canvas is not
# assignable here (LL-036/LL-037 — measured capability beats catalog claims).
_ALLOCATION_ASPECT = "16:9"


def is_gate_executable_kind(kind: str) -> bool:
    """Whether ``kind`` can currently survive deterministic plan lint."""
    return kind in integrated_kinds() and kind not in GATE_ILLEGAL_KINDS


def _is_allocatable_kind(kind: str) -> bool:
    """Gate-executable AND aspect-legal on the allocation lane's canvas."""
    return is_gate_executable_kind(kind) \
        and is_aspect_legal_kind(kind, _ALLOCATION_ASPECT)


def _normalized(beats: list[dict]) -> list[dict]:
    """Return one stable row per beat without trusting catalog order."""
    rows, seen = [], set()
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("beatId") or "")
        if not beat_id or beat_id in seen:
            continue
        seen.add(beat_id)
        forms = sorted({str(kind) for kind in beat.get("compatibleKinds") or []
                        if isinstance(kind, str)
                        and _is_allocatable_kind(kind)})
        rows.append({"beatId": beat_id, "compatibleKinds": forms,
                     "outStart": float(beat.get("outStart") or 0.0)})
    return rows


def _candidate_order(row: dict, preferred: Mapping[str, str]) -> list[str]:
    forms = row["compatibleKinds"]
    first = preferred.get(row["beatId"])
    if first not in forms:
        return forms
    return [first, *(kind for kind in forms if kind != first)]


def _maximum_matching(rows: list[dict],
                      preferred: Mapping[str, str]) -> dict[str, str]:
    by_id = {row["beatId"]: row for row in rows}
    owner: dict[str, str] = {}
    assigned: dict[str, str] = {}

    def augment(beat_id: str, seen: set[str]) -> bool:
        for kind in _candidate_order(by_id[beat_id], preferred):
            if kind in seen:
                continue
            seen.add(kind)
            prior = owner.get(kind)
            if prior is not None and not augment(prior, seen):
                continue
            owner[kind] = beat_id
            assigned[beat_id] = kind
            return True
        return False

    order = sorted(rows, key=lambda row: (len(row["compatibleKinds"]),
                                          row["beatId"]))
    for row in order:
        augment(row["beatId"], set())
    return assigned


def _complete_assignment(rows: list[dict],
                         assigned: dict[str, str]) -> dict[str, str]:
    """Give unmatched assignable beats a least-reused legal form."""
    completed = dict(assigned)
    counts = Counter(completed.values())
    for row in sorted(rows, key=lambda item: (item["outStart"], item["beatId"])):
        if row["beatId"] in completed or not row["compatibleKinds"]:
            continue
        kind = min(row["compatibleKinds"], key=lambda item: (counts[item], item))
        completed[row["beatId"]] = kind
        counts[kind] += 1
    return completed


def build_form_allocation(beats: list[dict],
                          preferred: Mapping[str, str] | None = None,
                          selected_profile: str | None = None) -> dict:
    """Return a stable maximum-distinct compatible assignment witness."""
    if selected_profile is not None:
        raise ValueError("Legacy visual profiles are retired; select the HyperFrames catalog")
    rows = _normalized(beats)
    unique = _maximum_matching(rows, preferred or {})
    complete = _complete_assignment(rows, unique)
    ordered = sorted(rows, key=lambda row: (row["outStart"], row["beatId"]))
    assignment = [{"beatId": row["beatId"], "kind": complete[row["beatId"]]}
                  for row in ordered if row["beatId"] in complete]
    return {
        "beatCount": len(rows),
        "assignableBeatCount": len(assignment),
        "maximumFeasibleDistinctKinds": len(unique),
        "recommendedAssignment": assignment,
        "unassignableBeatIds": [row["beatId"] for row in ordered
                                if row["beatId"] not in complete],
    }


def assess_kind_reuse(beats: list[dict], decisions: list[dict]) -> dict:
    """Compare selected legal graphic forms with their global optimum."""
    rows = _normalized(beats)
    by_id = {row["beatId"]: row for row in rows}
    chosen: dict[str, str] = {}
    for decision in decisions:
        if not isinstance(decision, dict) \
                or decision.get("decision") != "graphic":
            continue
        beat_id = str(decision.get("beatId") or "")
        kind = str(decision.get("kind") or "")
        beat = by_id.get(beat_id)
        if beat and beat_id not in chosen and kind in beat["compatibleKinds"]:
            chosen[beat_id] = kind
    selected = [by_id[beat_id] for beat_id in chosen]
    allocation = build_form_allocation(selected, chosen)
    recommended = {row["beatId"]: row["kind"]
                   for row in allocation["recommendedAssignment"]}
    witnesses = [{"beatId": beat_id, "chosenKind": kind,
                  "replacementKind": recommended[beat_id]}
                 for beat_id, kind in sorted(chosen.items())
                 if recommended.get(beat_id) != kind]
    actual = len(set(chosen.values()))
    maximum = allocation["maximumFeasibleDistinctKinds"]
    return {"selectedGraphicBeats": len(chosen),
            "selectedDistinctKinds": actual,
            "maximumFeasibleDistinctKinds": maximum,
            "avoidableReuse": actual < maximum,
            "replacementWitnesses": witnesses}


def assess_profile_form_reuse(beats: list[dict], decisions: list[dict],
                              selected_profile: str) -> dict:
    """Reject historical style allocation instead of offering house renderers."""
    raise ValueError("Legacy visual profiles are retired; select the HyperFrames catalog")

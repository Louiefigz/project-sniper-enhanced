"""Deterministic maximum-distinct assignment for semantic graphic forms."""
from __future__ import annotations

from collections import Counter
from typing import Mapping

from graphics.comp_capabilities import is_aspect_legal_kind
from graphics.style_profiles import form_contract, profile

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
    return bool(kind) and kind not in GATE_ILLEGAL_KINDS


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


def _profile_rows(beats: list[dict], selected_profile: str) -> list[dict]:
    rows, seen = [], set()
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("beatId") or "")
        if not beat_id or beat_id in seen:
            continue
        seen.add(beat_id)
        forms = []
        for information_form in beat.get("compatibleForms") or []:
            contract = form_contract(selected_profile, str(information_form))
            if contract and _is_allocatable_kind(str(contract.get("kind") or "")):
                forms.append(str(information_form))
        rows.append({"beatId": beat_id, "compatibleKinds": forms,
                     "preferredForm": beat.get("preferredForm"),
                     "outStart": float(beat.get("outStart") or 0.0)})
    return sorted(rows, key=lambda row: (row["outStart"], row["beatId"]))


def _profile_step_score(row: dict, information_form: str, used: frozenset,
                        dense_used: frozenset, previous: dict | None,
                        selected_profile: str) -> int:
    contract = form_contract(selected_profile, information_form) or {}
    rank = row["compatibleKinds"].index(information_form)
    score = 1000 if information_form not in used else -140
    if row.get("denseWindow"):
        score += 700 if information_form not in dense_used else -80
    score += max(0, 60 - rank * 12)
    if row.get("preferredForm") == information_form:
        score += 25
    if previous:
        prior = form_contract(selected_profile, previous["form"]) or {}
        score += 20 if prior.get("chassis") != contract.get("chassis") else -4
        score += 8 if prior.get("kind") != contract.get("kind") else 0
        if previous["form"] == information_form:
            score -= 200
    return score


def _profile_limits(beats: list[dict], selected_profile: str
                    ) -> tuple[list[dict], int, int]:
    """Mark the dense window and compute global/local matching ceilings."""
    rows = _profile_rows(beats, selected_profile)
    cfg = profile(selected_profile) or {}
    dense_start = float(cfg.get("denseWindowStartS", 0.0))
    dense_end = float(cfg.get("denseWindowEndS", 0.0))
    for row in rows:
        row["denseWindow"] = dense_start <= row["outStart"] < dense_end
    preferred = {row["beatId"]: row.get("preferredForm") for row in rows}
    maximum = len(_maximum_matching(rows, preferred))
    dense_rows = [row for row in rows if row["denseWindow"]]
    dense_maximum = len(_maximum_matching(dense_rows, preferred))
    return rows, maximum, dense_maximum


def _advance_profile_states(states: list[tuple], row: dict,
                            selected_profile: str) -> list[tuple]:
    """Advance and dominance-prune one row of the bounded profile beam."""
    next_states = []
    for score, used, dense_used, assignment in states:
        previous = assignment[-1] if assignment else None
        for information_form in row["compatibleKinds"]:
            contract = form_contract(selected_profile, information_form) or {}
            item = {"beatId": row["beatId"], "informationForm": information_form,
                    "kind": contract.get("kind"),
                    "chassis": contract.get("chassis"),
                    "form": information_form}
            delta = _profile_step_score(
                row, information_form, used, dense_used, previous,
                selected_profile)
            next_dense = dense_used | {information_form} \
                if row["denseWindow"] else dense_used
            next_states.append((score + delta, used | {information_form},
                                next_dense, [*assignment, item]))
    best = {}
    for state in next_states:
        key = (state[1], state[2], state[3][-1]["form"])
        if key not in best or state[0] > best[key][0]:
            best[key] = state
    return sorted(best.values(), key=lambda state: (
        len(state[1]), len(state[2]), state[0],
        tuple(item["form"] for item in state[3])), reverse=True)[:512]


def _choose_profile_assignment(states: list[tuple], maximum: int,
                               dense_maximum: int) -> tuple[list[dict], int]:
    """Choose a state meeting both matching ceilings when one exists."""
    if not states:
        return [], 0
    eligible = [state for state in states if len(state[1]) == maximum
                and len(state[2]) == dense_maximum]
    chosen = max(eligible or states, key=lambda state: (
        len(state[1]), len(state[2]), state[0]))
    assignment = [{key: value for key, value in item.items() if key != "form"}
                  for item in chosen[3]]
    return assignment, len(chosen[2])


def _profile_allocation(beats: list[dict], selected_profile: str) -> dict:
    """Beam-search a maximum-form sequence, then optimize chassis rhythm."""
    rows, maximum, dense_maximum = _profile_limits(beats, selected_profile)
    # State: score, all forms, dense-window forms, assignments.
    states: list[tuple] = [(0, frozenset(), frozenset(), [])]
    for row in rows:
        if row["compatibleKinds"]:
            states = _advance_profile_states(states, row, selected_profile)
    assignment, dense_selected = _choose_profile_assignment(
        states, maximum, dense_maximum)
    kinds = {str(item.get("kind")) for item in assignment if item.get("kind")}
    forms = {str(item.get("informationForm")) for item in assignment
             if item.get("informationForm")}
    return {"beatCount": len(rows), "assignableBeatCount": len(assignment),
            "maximumFeasibleDistinctKinds": len(kinds),
            "maximumFeasibleDistinctForms": maximum,
            "denseWindowMaximumFeasibleDistinctForms": dense_maximum,
            "denseWindowSelectedDistinctForms": dense_selected,
            "selectedDistinctForms": len(forms),
            "recommendedAssignment": assignment,
            "unassignableBeatIds": [row["beatId"] for row in rows
                                    if not row["compatibleKinds"]],
            "visualProfile": selected_profile}


def build_form_allocation(beats: list[dict],
                          preferred: Mapping[str, str] | None = None,
                          selected_profile: str | None = None) -> dict:
    """Return a stable maximum-distinct compatible assignment witness."""
    if selected_profile:
        return _profile_allocation(beats, selected_profile)
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
    """Compare selected profile information forms with their global optimum."""
    rows = _profile_rows(beats, selected_profile)
    by_id = {row["beatId"]: row for row in rows}
    source_by_id = {str(row.get("beatId")): row for row in beats
                    if isinstance(row, dict) and row.get("beatId")}
    chosen: dict[str, str] = {}
    for decision in decisions:
        if not isinstance(decision, dict) \
                or decision.get("decision") != "graphic":
            continue
        beat_id = str(decision.get("beatId") or "")
        information_form = str(decision.get("informationForm") or "")
        beat = by_id.get(beat_id)
        if beat and beat_id not in chosen \
                and information_form in beat["compatibleKinds"]:
            chosen[beat_id] = information_form
    selected = [source_by_id[beat_id] for beat_id in chosen]
    allocation = build_form_allocation(
        selected, selected_profile=selected_profile)
    recommended = {row["beatId"]: row["informationForm"]
                   for row in allocation["recommendedAssignment"]}
    witnesses = [{"beatId": beat_id,
                  "chosenInformationForm": information_form,
                  "replacementInformationForm": recommended[beat_id]}
                 for beat_id, information_form in sorted(chosen.items())
                 if recommended.get(beat_id) != information_form]
    actual = len(set(chosen.values()))
    maximum = allocation["maximumFeasibleDistinctForms"]
    return {"selectedGraphicBeats": len(chosen),
            "selectedDistinctForms": actual,
            "maximumFeasibleDistinctForms": maximum,
            "avoidableReuse": actual < maximum,
            "replacementWitnesses": witnesses,
            "visualProfile": selected_profile}

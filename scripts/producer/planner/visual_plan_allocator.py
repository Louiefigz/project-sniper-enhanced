"""Deterministic, memory-bounded whole-video visual allocation."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from planner.visual_plan_contract import (
    VisualPlanContractError,
    validate_visual_plan,
)
from planner.visual_plan_admission import derived_project_route
from planner.visual_plan_allocator_ranking import RankingState, candidate_score
from planner.visual_plan_layering import (
    VisualWindow, advance_visual_windows, breathing_conflict,
)
from planner.visual_plan_source_identity import source_identity, source_repeat_differs


@dataclass(frozen=True)
class _State:
    """One bounded beam-search state."""

    picks: tuple[str, ...]
    score: tuple[int, ...]
    section_counts: tuple[tuple[str, int], ...]
    development_counts: tuple[tuple[str, int], ...]
    source_counts: tuple[tuple[str, int], ...]
    last_family: str | None
    last_development: str | None
    consecutive_family: int
    visual_windows: tuple[VisualWindow, ...]


def allocate_visual_plan(value: object,
                         receipt_authority: dict | None = None) -> dict:
    """Allocate all opportunities and return a validated frozen plan copy."""
    plan = validate_visual_plan(value, receipt_authority)
    if plan["allocation"]["status"] != "pending":
        raise VisualPlanContractError("allocator requires a pending visual plan")
    opportunities = sorted(
        plan["opportunities"],
        key=lambda row: (row["timing"]["startFrame"], row["id"]),
    )
    states = [_empty_state()]
    for opportunity in opportunities:
        states = _expand_beam(plan, opportunity, states)
    winner = states[0]
    selected = _selected_candidates(opportunities, winner.picks)
    route = derived_project_route(plan["project"]["mode"], selected)
    decisions = _build_decisions(plan, opportunities, winner, route)
    plan["allocation"] = {
        "status": "allocated",
        "allocatorVersion": "visual-plan-allocator-v1",
        "route": route,
        "decisions": decisions,
        "unresolvedAmbiguity": _allocation_ambiguity(opportunities, selected),
    }
    return validate_visual_plan(plan, receipt_authority)


def _empty_state() -> _State:
    return _State((), (0,) * 9, (), (), (), None, None, 0, ())


def _expand_beam(plan: dict, opportunity: dict,
                 states: list[_State]) -> list[_State]:
    candidates = sorted(opportunity["candidates"], key=lambda row: row["id"])
    expanded = [
        _advance(plan, opportunity, candidate, state)
        for state in states
        for candidate in candidates
        if candidate["eligibility"] == "eligible"
        and not _budget_conflict(plan, opportunity, candidate, state)
    ]
    if not expanded:
        raise VisualPlanContractError(
            f"no eligible allocation satisfies budgets for {opportunity['id']}")
    expanded.sort(key=lambda row: (tuple(-value for value in row.score), row.picks))
    return expanded[:plan["bounds"]["allocatorBeamWidth"]]


def _budget_conflict(plan: dict, opportunity: dict,
                     candidate: dict, state: _State) -> str | None:
    intent_conflict = _repeat_intent_conflict(plan, opportunity, candidate, state)
    if intent_conflict:
        return intent_conflict
    if not _is_visual(candidate):
        return None
    density = plan["direction"]["density"]
    section_count = dict(state.section_counts).get(opportunity["sectionId"], 0)
    if section_count >= density["maxVisualsPerSection"]:
        return "section visual-density budget"
    if breathing_conflict(plan, opportunity, state.visual_windows):
        return "breathing-room budget"
    repeat = plan["direction"]["repetition"]
    family = candidate["composition"]["familyId"]
    if state.last_family == family:
        if state.consecutive_family >= repeat["maxConsecutiveFamily"]:
            return "consecutive-family repetition budget"
    development = _development_key(candidate)
    count = dict(state.development_counts).get(development, 0)
    if count > 0 and candidate.get("repeatIntent") is None:
        return "identical development requires an intentional repeat reason"
    if count >= repeat["maxIdenticalDevelopment"]:
        return "identical-development repetition budget"
    source_key = _source_key(candidate)
    source_count = dict(state.source_counts).get(source_key, 0)
    if source_key and source_count > 0 and candidate.get("repeatIntent") is None:
        return "stable source identity requires an intentional repeat reason"
    if source_key and source_count >= repeat["maxIdenticalDevelopment"]:
        return "stable-source repetition budget"
    return None


def _repeat_intent_conflict(plan: dict, opportunity: dict,
                            candidate: dict, state: _State) -> str | None:
    intent = candidate.get("repeatIntent")
    if intent is None:
        return None
    prior = _selected_prior(plan, state, intent["priorOpportunityId"])
    if prior is None or prior["candidate"]["id"] != intent["priorCandidateId"]:
        return "repeat intent does not bind an actual prior selection"
    if prior["candidate"]["composition"] != candidate["composition"]:
        return "repeat intent composition differs from its prior selection"
    if source_repeat_differs(prior["candidate"], candidate):
        return "repeat intent source differs from its prior selection"
    relation = "callbackTo" if intent["classification"] == "callback" else "continuityWith"
    if prior["opportunity"]["id"] not in opportunity[relation]:
        return "repeat intent is not bound by the opportunity relationship"
    return None


def _selected_prior(plan: dict, state: _State, opportunity_id: str) -> dict | None:
    opportunities = sorted(
        plan["opportunities"],
        key=lambda row: (row["timing"]["startFrame"], row["id"]),
    )
    for opportunity, candidate_id in zip(opportunities, state.picks):
        if opportunity["id"] != opportunity_id:
            continue
        candidate = next(row for row in opportunity["candidates"]
                         if row["id"] == candidate_id)
        return {"opportunity": opportunity, "candidate": candidate}
    return None


def _advance(plan: dict, opportunity: dict,
             candidate: dict, state: _State) -> _State:
    ranking = RankingState(
        state.source_counts, state.development_counts, state.last_family)
    increment = candidate_score(plan, candidate, ranking)
    score = tuple(left + right for left, right in zip(state.score, increment))
    if not _is_visual(candidate):
        return _State(state.picks + (candidate["id"],), score,
                      state.section_counts, state.development_counts,
                      state.source_counts,
                      state.last_family, state.last_development,
                      state.consecutive_family,
                      state.visual_windows)
    sections = dict(state.section_counts)
    sections[opportunity["sectionId"]] = sections.get(opportunity["sectionId"], 0) + 1
    development = dict(state.development_counts)
    key = _development_key(candidate)
    development[key] = development.get(key, 0) + 1
    sources = dict(state.source_counts)
    source_key = _source_key(candidate)
    if source_key:
        sources[source_key] = sources.get(source_key, 0) + 1
    family = candidate["composition"]["familyId"]
    consecutive = state.consecutive_family + 1 if family == state.last_family else 1
    return _State(
        state.picks + (candidate["id"],), score, tuple(sorted(sections.items())),
        tuple(sorted(development.items())), tuple(sorted(sources.items())),
        family, key, consecutive,
        advance_visual_windows(plan, opportunity, state.visual_windows),
    )


def _development_key(candidate: dict) -> str:
    composition = candidate["composition"]
    return "\x1f".join((composition["familyId"], composition["anatomy"],
                         composition["development"]))


def _source_key(candidate: dict) -> str | None:
    identity = source_identity(candidate)
    return "\x1f".join(identity) if identity else None


def _is_visual(candidate: dict) -> bool:
    return candidate["modality"] not in {"presenter", "omit"}


def _selected_candidates(opportunities: list[dict], picks: tuple[str, ...]) -> list[dict]:
    selected = []
    for opportunity, candidate_id in zip(opportunities, picks):
        candidate = next(row for row in opportunity["candidates"]
                         if row["id"] == candidate_id)
        selected.append(candidate)
    return selected


def _build_decisions(plan: dict, opportunities: list[dict],
                     winner: _State, route: str) -> list[dict]:
    decisions = []
    state = _empty_state()
    for opportunity, candidate_id in zip(opportunities, winner.picks):
        candidate = next(row for row in opportunity["candidates"]
                         if row["id"] == candidate_id)
        classification, reason = _repeat_classification(candidate, state)
        decisions.append({
            "opportunityId": opportunity["id"], "candidateId": candidate["id"],
            "modality": candidate["modality"], "executionRoute": route,
            "decisionReason": candidate["decisionReason"],
            "confidence": candidate["confidence"],
            "unresolvedAmbiguity": candidate["unresolvedAmbiguity"],
            "repeatClassification": classification, "repeatReason": reason,
            "alternatives": _alternatives(plan, opportunity, candidate, state),
        })
        state = _advance(plan, opportunity, candidate, state)
    return decisions


def _repeat_classification(candidate: dict, state: _State) -> tuple[str, str]:
    intent = candidate.get("repeatIntent")
    if intent:
        return intent["classification"], intent["reason"]
    if not _is_visual(candidate):
        return "none", ""
    family = candidate["composition"]["familyId"]
    development = _development_key(candidate)
    if development == state.last_development:
        raise VisualPlanContractError("identical development lost its repeat intent")
    if family == state.last_family:
        return "varied", "Same family with a different anatomy or development."
    return "none", ""


def _alternatives(plan: dict, opportunity: dict,
                  selected: dict, state: _State) -> list[dict]:
    alternatives = []
    for candidate in sorted(opportunity["candidates"], key=lambda row: row["id"]):
        if candidate["id"] == selected["id"]:
            continue
        if candidate["eligibility"] != "eligible":
            outcome, reason = "ineligible", _ineligible_reason(candidate)
        else:
            conflict = _budget_conflict(plan, opportunity, candidate, state)
            outcome = "budget-conflict" if conflict else "lower-ranked"
            reason = conflict or (
                "Lower quality-band rank after variation and recent-use evidence.")
        alternatives.append({"candidateId": candidate["id"],
                             "outcome": outcome, "reason": reason})
    return alternatives[:4]


def _ineligible_reason(candidate: dict) -> str:
    reasons = candidate["exclusionReasons"] or candidate["prerequisites"]
    return reasons[0] if reasons else "Candidate is not currently executable."


def _allocation_ambiguity(opportunities: list[dict],
                          selected: list[dict]) -> list[str]:
    rows = []
    for opportunity, candidate in zip(opportunities, selected):
        rows.extend(opportunity["unresolvedAmbiguity"])
        rows.extend(candidate["unresolvedAmbiguity"])
    return list(dict.fromkeys(rows))[:32]

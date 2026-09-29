"""Quality-banded ranking for deterministic visual-plan allocation."""
from __future__ import annotations

from dataclasses import dataclass

from planner.visual_plan_source_identity import source_identity

QUALITY_EQUIVALENCE_BAND = 0.05


@dataclass(frozen=True)
class RankingState:
    """Bounded prior-use facts that affect candidate variation."""

    source_counts: tuple[tuple[str, int], ...]
    development_counts: tuple[tuple[str, int], ...]
    last_family: str | None


def candidate_score(plan: dict, candidate: dict,
                    state: RankingState) -> tuple[int, ...]:
    """Rank variation first only inside a documented quality-equivalent band."""
    scores = candidate["scores"]
    quality = _quality(scores)
    quality_band = round(quality / QUALITY_EQUIVALENCE_BAND)
    variation = _variation_score(plan, candidate, state)
    ordered = (
        quality_band, variation, -scores["recentReusePenalty"], quality,
        scores["validity"], scores["semanticFit"], scores["readability"],
        scores["feasibility"], scores["coherence"],
    )
    return tuple(round(value * 1000) for value in ordered)


def _quality(scores: dict) -> float:
    """Combine execution trust and visual usefulness without filler rotation."""
    return (scores["validity"] * 0.30 + scores["semanticFit"] * 0.35
            + scores["readability"] * 0.15 + scores["feasibility"] * 0.10
            + scores["coherence"] * 0.10)


def _variation_score(plan: dict, candidate: dict,
                     state: RankingState) -> float:
    score = candidate["scores"]["variation"]
    composition = candidate["composition"]
    for used in plan["relatedUsage"]:
        if _same_used_source(used, candidate):
            score -= 0.30
        elif _same_development(used, composition):
            score -= 0.18
        elif used["familyId"] == composition["familyId"]:
            score -= 0.05
    source_key = _source_key(candidate)
    if source_key and dict(state.source_counts).get(source_key, 0):
        score -= 0.30
    development = _development_key(candidate)
    if dict(state.development_counts).get(development, 0):
        score -= 0.12
    elif state.last_family == composition["familyId"]:
        score -= 0.03
    return max(0.0, min(1.0, score))


def _same_used_source(used: dict, candidate: dict) -> bool:
    key = source_identity(candidate)
    return key is not None and key == (
        used["modality"], used["sourceRecordId"], used["sourceSha256"])


def _same_development(left: dict, right: dict) -> bool:
    return (left["familyId"], left["anatomy"], left["development"]) == (
        right["familyId"], right["anatomy"], right["development"])


def _development_key(candidate: dict) -> str:
    composition = candidate["composition"]
    return "\x1f".join((composition["familyId"], composition["anatomy"],
                         composition["development"]))


def _source_key(candidate: dict) -> str | None:
    key = source_identity(candidate)
    return "\x1f".join(key) if key else None

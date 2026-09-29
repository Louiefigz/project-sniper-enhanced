"""Bind every visual opportunity to reproducible semantic-search evidence."""
from __future__ import annotations

import re

from planner.ordinary_visual_plan_search import validate_search_authority
from planner.visual_plan_fields import (
    VisualPlanContractError, id_field, object_field, sha_field, text_field,
)

_TOKEN = re.compile(r"[a-z0-9]+")
_GENERIC = {"a", "an", "and", "as", "at", "be", "for", "from", "in",
            "is", "it", "of", "on", "or", "that", "the", "this", "to", "with"}


def validate_plan_search_evidence(plan: dict, opportunities: list[dict]) -> None:
    """Require exact coverage or rejection of every credible retrieved record."""
    try:
        document = validate_search_authority(
            plan["searchAuthority"], plan["catalogPin"])
    except (KeyError, OSError, TypeError, ValueError) as exc:
        if isinstance(exc, VisualPlanContractError):
            raise
        raise VisualPlanContractError(str(exc)) from exc
    searches = document.get("searches")
    if not isinstance(searches, list):
        raise VisualPlanContractError("search authority searches must be an array")
    expected_ids = [row["id"] for row in opportunities]
    actual_ids = [row.get("opportunityId") if isinstance(row, dict) else None
                  for row in searches]
    if actual_ids != expected_ids:
        raise VisualPlanContractError(
            "search authority must cover every opportunity in plan order")
    for opportunity, search in zip(opportunities, searches):
        _validate_opportunity_review(
            opportunity, search, plan["searchAuthority"]["digest"])


def _credible_records(search: dict, name: str) -> list[str]:
    results = search.get("results")
    if not isinstance(results, list) or len(results) > 5:
        raise VisualPlanContractError(f"{name} search results exceed the five-item bound")
    records = []
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            raise VisualPlanContractError(f"{name} search result {index} is invalid")
        record_id = id_field(result.get("id"), f"{name} search result {index} id")
        credibility = result.get("credibility")
        if not isinstance(credibility, dict) or credibility.get("status") not in {
                "credible", "weak"}:
            raise VisualPlanContractError(
                f"{name} search result {index} lacks controller credibility")
        if credibility["status"] == "credible":
            records.append(record_id)
    return records


def _review_rows(value: object, name: str, digest: str) -> list[dict]:
    review = object_field(value, f"{name} searchReview",
                          {"searchDigest", "outcomes"}, set())
    sha_field(review["searchDigest"], f"{name} searchReview searchDigest")
    if review["searchDigest"] != digest:
        raise VisualPlanContractError(
            f"{name} searchReview names stale search evidence")
    outcomes = review["outcomes"]
    if not isinstance(outcomes, list) or len(outcomes) > 5:
        raise VisualPlanContractError(f"{name} searchReview outcomes exceed five")
    rows = []
    for index, value in enumerate(outcomes):
        row = object_field(
            value, f"{name} search outcome {index}",
            {"recordId", "outcome", "candidateId", "reason"}, set())
        id_field(row["recordId"], f"{name} search outcome {index} recordId")
        text_field(row["reason"], f"{name} search outcome {index} reason")
        if row["outcome"] not in {"candidate", "rejected"}:
            raise VisualPlanContractError(f"{name} search outcome is invalid")
        if row["outcome"] == "candidate":
            id_field(row["candidateId"], f"{name} search outcome candidateId")
        elif row["candidateId"] is not None:
            raise VisualPlanContractError(
                f"{name} rejected search outcome cannot name a candidate")
        rows.append(row)
    return rows


def _validate_opportunity_review(opportunity: dict, search: dict,
                                 digest: str) -> None:
    name = f"opportunity {opportunity['id']}"
    _validate_query_anchor(opportunity, search, name)
    credible = _credible_records(search, name)
    rows = _review_rows(opportunity["searchReview"], name, digest)
    if [row["recordId"] for row in rows] != credible:
        raise VisualPlanContractError(
            f"{name} searchReview must cover every credible result in rank order")
    candidates = {row["id"]: row for row in opportunity["candidates"]}
    for review in rows:
        matching = [candidate for candidate in candidates.values()
                    if candidate["modality"] == "catalog"
                    and candidate["source"] is not None
                    and candidate["source"]["recordId"] == review["recordId"]]
        if review["outcome"] == "rejected":
            if matching:
                raise VisualPlanContractError(
                    f"{name} rejects a credible result retained as a candidate")
            continue
        candidate = candidates.get(review["candidateId"])
        if candidate not in matching:
            raise VisualPlanContractError(
                f"{name} search outcome does not bind its catalog candidate")


def _validate_query_anchor(opportunity: dict, search: dict, name: str) -> None:
    semantic = [opportunity[key] for key in (
        "viewerQuestion", "explanatoryJob", "sectionRole", "attentionState")]
    semantic.append(opportunity["transcriptEvidence"]["text"])
    semantic.extend(item for values in opportunity["requirements"].values()
                    for item in values)
    opportunity_terms = {term for value in semantic
                         for term in _TOKEN.findall(value.lower())
                         if term not in _GENERIC}
    query_terms = {term for term in search.get("directTerms", [])
                   if term not in _GENERIC}
    if not opportunity_terms & query_terms:
        raise VisualPlanContractError(
            f"{name} semantic query is not anchored to its transcript or visual job")

"""Cross-record validation for route-neutral visual plans."""
from __future__ import annotations

from planner.visual_plan_fields import (
    MODALITIES, ROUTES, VisualPlanContractError, id_field, number_field,
    object_field, strings_field, text_field, validate_candidate,
    validate_header_fields, validate_timing, sha_field,
)
from planner.visual_plan_admission import (
    derived_project_route, load_catalog_authority, validate_plan_pins,
)
from planner.visual_plan_controller_authority import validate_controller_authorities
from planner.visual_plan_related_usage import validate_related_use
from planner.visual_plan_layering import validate_layering
from planner.visual_plan_search_evidence import validate_plan_search_evidence
from planner.visual_plan_source_identity import same_source, source_identity, source_repeat_differs


def validate_plan_structure(plan: dict,
                            receipt_authority: dict | None = None) -> None:
    """Validate all plan records and their cross-record identities."""
    validate_header_fields(plan)
    authority = load_catalog_authority(plan["catalogPin"])
    opportunities = plan["opportunities"]
    limit = plan["bounds"]["maxOpportunities"]
    if not isinstance(opportunities, list) or not 1 <= len(opportunities) <= limit:
        raise VisualPlanContractError("opportunities exceed the declared bound")
    _validate_related_usage(plan["relatedUsage"])
    validated = [_validate_opportunity(row, index, plan)
                 for index, row in enumerate(opportunities)]
    opportunity_ids = [row["id"] for row in validated]
    candidate_ids = [candidate["id"] for row in validated
                     for candidate in row["candidates"]]
    if len(opportunity_ids) != len(set(opportunity_ids)):
        raise VisualPlanContractError("opportunity IDs must be globally unique")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise VisualPlanContractError("candidate IDs must be globally unique")
    _validate_relationships(validated)
    validate_layering(validated)
    _validate_repeat_references(validated)
    media_authority = validate_controller_authorities(plan, validated)
    validate_plan_search_evidence(plan, validated)
    _validate_allocation(plan)
    validate_plan_pins(plan, authority, media_authority, receipt_authority)


def _validate_opportunity(value: object, index: int, plan: dict) -> dict:
    required = {"id", "beatId", "kind", "sectionId", "timing", "transcriptEvidence",
                "viewerQuestion", "explanatoryJob", "sectionRole", "attentionState",
                "evidenceSensitivity", "importance", "maxUsefulHoldFrames", "requirements",
                "allowedModalities", "prohibitedModalities", "callbackTo", "continuityWith",
                "confidence", "unresolvedAmbiguity", "searchReview", "candidates"}
    row = object_field(value, f"opportunity {index}", required, {"seamContext", "layering"})
    for key in ("id", "beatId", "sectionId"):
        id_field(row[key], f"opportunity {index} {key}")
    if row["kind"] not in {"beat", "seam", "chapter", "persistent", "callback"}:
        raise VisualPlanContractError(f"opportunity {index} kind is invalid")
    validate_timing(row["timing"], f"opportunity {index} timing",
                    plan["project"]["durationFrames"])
    _validate_opportunity_context(row, index)
    candidates = row["candidates"]
    bound = plan["bounds"]["maxCandidatesPerOpportunity"]
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= bound:
        raise VisualPlanContractError(
            f"opportunity {index} candidates exceed the declared bound")
    for candidate_index, candidate in enumerate(candidates):
        name = f"opportunity {index} candidate {candidate_index}"
        item = validate_candidate(candidate, name, plan["bounds"])
        if item["modality"] not in row["allowedModalities"]:
            raise VisualPlanContractError(f"candidate {item['id']} is not allowed")
        if item["modality"] in row["prohibitedModalities"]:
            raise VisualPlanContractError(f"candidate {item['id']} is prohibited")
        if item["modality"] == "transition" and row["kind"] != "seam":
            raise VisualPlanContractError("transition candidates require a seam")
    return row


def _validate_opportunity_context(row: dict, index: int) -> None:
    evidence = object_field(
        row["transcriptEvidence"], f"opportunity {index} transcriptEvidence",
        {"text", "wordIds"}, set())
    text_field(evidence["text"], f"opportunity {index} transcript text")
    strings_field(evidence["wordIds"], f"opportunity {index} word IDs", 64)
    for key in ("viewerQuestion", "explanatoryJob", "sectionRole", "attentionState"):
        text_field(row[key], f"opportunity {index} {key}")
    number_field(row["importance"], f"opportunity {index} importance")
    number_field(row["confidence"], f"opportunity {index} confidence")
    if row["evidenceSensitivity"] not in {"low", "medium", "high"}:
        raise VisualPlanContractError(f"opportunity {index} evidence sensitivity is invalid")
    if type(row["maxUsefulHoldFrames"]) is not int or row["maxUsefulHoldFrames"] < 1:
        raise VisualPlanContractError(f"opportunity {index} maximum hold is invalid")
    requirements = object_field(row["requirements"], f"opportunity {index} requirements",
                                {"visibleSubjects", "quantities", "relationships", "actions"}, set())
    for key, value in requirements.items():
        strings_field(value, f"opportunity {index} requirement {key}")
    for key in ("callbackTo", "continuityWith"):
        values = strings_field(row[key], f"opportunity {index} {key}", 64)
        for value in values:
            id_field(value, f"opportunity {index} {key} item")
    strings_field(row["unresolvedAmbiguity"], f"opportunity {index} ambiguity")
    for key in ("allowedModalities", "prohibitedModalities"):
        modalities = row[key]
        if not isinstance(modalities, list) or any(item not in MODALITIES for item in modalities):
            raise VisualPlanContractError(f"opportunity {index} {key} is invalid")
        if len(modalities) != len(set(modalities)):
            raise VisualPlanContractError(f"opportunity {index} {key} has duplicates")
    if not row["allowedModalities"]:
        raise VisualPlanContractError(f"opportunity {index} needs an allowed modality")
    if set(row["allowedModalities"]) & set(row["prohibitedModalities"]):
        raise VisualPlanContractError(f"opportunity {index} modality lists overlap")
    if row["kind"] == "seam":
        _validate_seam(row.get("seamContext"), index)
    elif "seamContext" in row:
        raise VisualPlanContractError("only seam opportunities may carry seamContext")


def _validate_seam(value: object, index: int) -> None:
    seam = object_field(value, f"opportunity {index} seamContext",
                        {"left", "right", "relationship"}, set())
    text_field(seam["relationship"], f"opportunity {index} seam relationship")
    side_keys = {"sceneId", "motion", "composition", "color", "audio", "narrative"}
    for side_name in ("left", "right"):
        side = object_field(seam[side_name], f"seam {side_name}", side_keys, set())
        id_field(side["sceneId"], f"seam {side_name} sceneId")
        for key in side_keys - {"sceneId"}:
            text_field(side[key], f"seam {side_name} {key}")
    if seam["left"]["sceneId"] == seam["right"]["sceneId"]:
        raise VisualPlanContractError("seam context must name two different scenes")


def _validate_related_usage(value: object) -> None:
    if not isinstance(value, list) or len(value) > 128:
        raise VisualPlanContractError("relatedUsage must be bounded")
    for index, usage in enumerate(value):
        validate_related_use(usage, f"related usage {index}")


def _validate_relationships(opportunities: list[dict]) -> None:
    ids = {row["id"] for row in opportunities}
    for row in opportunities:
        _validate_relationship(row, "callbackTo", ids)
        _validate_relationship(row, "continuityWith", ids)


def _validate_relationship(row: dict, key: str, ids: set[str]) -> None:
    for target in row[key]:
        if target == row["id"] or target not in ids:
            raise VisualPlanContractError(
                f"opportunity {row['id']} has invalid {key} target")


def _validate_repeat_references(opportunities: list[dict]) -> None:
    by_id = {row["id"]: row for row in opportunities}
    for opportunity in opportunities:
        for candidate in opportunity["candidates"]:
            _validate_repeat_reference(opportunity, candidate, by_id)


def _validate_repeat_reference(opportunity: dict, candidate: dict,
                               by_id: dict[str, dict]) -> None:
    intent = candidate.get("repeatIntent")
    if intent is None:
        return
    prior = by_id.get(intent["priorOpportunityId"])
    if prior is None:
        raise VisualPlanContractError("repeat intent names an unknown opportunity")
    prior_candidates = {row["id"]: row for row in prior["candidates"]}
    previous = prior_candidates.get(intent["priorCandidateId"])
    if previous is None or prior["timing"]["startFrame"] >= opportunity["timing"]["startFrame"]:
        raise VisualPlanContractError("repeat intent must bind an earlier candidate")
    relation = "callbackTo" if intent["classification"] == "callback" else "continuityWith"
    if prior["id"] not in opportunity[relation]:
        raise VisualPlanContractError("repeat intent lacks its opportunity relationship")
    if previous["composition"] != candidate["composition"]:
        raise VisualPlanContractError("repeat intent composition does not match its prior use")
    if source_repeat_differs(previous, candidate):
        raise VisualPlanContractError("repeat intent source does not match its prior use")


def _validate_allocation(plan: dict) -> None:
    allocation = object_field(
        plan["allocation"], "allocation",
        {"status", "allocatorVersion", "route", "decisions", "unresolvedAmbiguity"}, set())
    if allocation["allocatorVersion"] != "visual-plan-allocator-v1":
        raise VisualPlanContractError("allocation allocatorVersion is unsupported")
    if allocation["status"] == "pending":
        if allocation["route"] != "pending" or allocation["decisions"]:
            raise VisualPlanContractError(
                "pending allocation cannot contain a route or decisions")
        return
    if allocation["status"] != "allocated" or allocation["route"] not in ROUTES:
        raise VisualPlanContractError("allocation status or route is invalid")
    ordered = sorted(plan["opportunities"],
                     key=lambda row: (row["timing"]["startFrame"], row["id"]))
    opportunities = {row["id"]: row for row in ordered}
    decisions = allocation["decisions"]
    if not isinstance(decisions, list) or len(decisions) != len(opportunities):
        raise VisualPlanContractError(
            "allocated decisions must cover every opportunity")
    decision_ids = [row.get("opportunityId") if isinstance(row, dict) else None
                    for row in decisions]
    if decision_ids != [row["id"] for row in ordered]:
        raise VisualPlanContractError(
            "allocation decisions must follow opportunity time order")
    selected: list[tuple[dict, dict]] = []
    for decision, opportunity in zip(decisions, ordered):
        candidate = _validate_decision(
            decision, allocation["route"], opportunity, selected)
        selected.append((opportunity, candidate))
    expected = derived_project_route(plan["project"]["mode"],
                                     [candidate for _, candidate in selected])
    if allocation["route"] != expected:
        raise VisualPlanContractError("allocation route differs from selected route classes")


def _validate_decision(decision: object, route: str, opportunity: dict,
                       selected: list[tuple[dict, dict]]) -> dict:
    keys = {"opportunityId", "candidateId", "modality", "executionRoute",
            "decisionReason", "confidence", "unresolvedAmbiguity",
            "repeatClassification", "repeatReason", "alternatives"}
    row = object_field(decision, "allocation decision", keys, set())
    opportunity_id = id_field(row["opportunityId"], "decision opportunityId")
    if opportunity_id != opportunity["id"]:
        raise VisualPlanContractError("decision opportunity does not match its position")
    candidates = {item["id"]: item for item in opportunity["candidates"]}
    candidate = candidates.get(row["candidateId"])
    if candidate is None or candidate["eligibility"] != "eligible":
        raise VisualPlanContractError("decision candidate is missing or ineligible")
    if row["modality"] != candidate["modality"] or row["executionRoute"] != route:
        raise VisualPlanContractError(
            "decision does not bind the candidate and project route")
    if route == "ordinary" and candidate["routeClass"] == "native":
        raise VisualPlanContractError(
            "native candidate cannot execute through the ordinary route")
    _validate_decision_details(row, candidate, opportunity, selected)
    _validate_alternatives(row["alternatives"], candidate, candidates)
    return candidate


def _validate_decision_details(row: dict, candidate: dict, opportunity: dict,
                               selected: list[tuple[dict, dict]]) -> None:
    if row["decisionReason"] != candidate["decisionReason"] \
            or row["confidence"] != candidate["confidence"] \
            or row["unresolvedAmbiguity"] != candidate["unresolvedAmbiguity"]:
        raise VisualPlanContractError("decision explanation differs from its candidate")
    expected_class, expected_reason = _expected_repeat(candidate, opportunity, selected)
    if (row["repeatClassification"], row["repeatReason"]) != (expected_class, expected_reason):
        raise VisualPlanContractError("decision repeat classification is not supported")


def _expected_repeat(candidate: dict, opportunity: dict,
                     selected: list[tuple[dict, dict]]) -> tuple[str, str]:
    intent = candidate.get("repeatIntent")
    if intent:
        prior = next((item for item in selected
                      if item[0]["id"] == intent["priorOpportunityId"]
                      and item[1]["id"] == intent["priorCandidateId"]), None)
        relation = "callbackTo" if intent["classification"] == "callback" else "continuityWith"
        if prior is None or prior[0]["id"] not in opportunity[relation]:
            raise VisualPlanContractError("allocated repeat does not bind the selected prior use")
        return intent["classification"], intent["reason"]
    if candidate["modality"] in {"presenter", "omit"}:
        return "none", ""
    key = _composition_key(candidate)
    if any(_composition_key(prior) == key for _, prior in selected):
        raise VisualPlanContractError("identical development lacks repeat intent")
    if source_identity(candidate) and any(
            same_source(prior, candidate) for _, prior in selected):
        raise VisualPlanContractError("stable source identity lacks repeat intent")
    previous_visual = next((prior for _, prior in reversed(selected)
                            if prior["modality"] not in {"presenter", "omit"}), None)
    if previous_visual and previous_visual["composition"]["familyId"] == candidate["composition"]["familyId"]:
        return "varied", "Same family with a different anatomy or development."
    return "none", ""
def _composition_key(candidate: dict) -> tuple[str, str, str]:
    composition = candidate["composition"]
    return (composition["familyId"], composition["anatomy"],
            composition["development"])
def _validate_alternatives(value: object, selected: dict,
                           candidates: dict[str, dict]) -> None:
    if not isinstance(value, list) or len(value) > 4:
        raise VisualPlanContractError("decision alternatives must be bounded")
    expected = sorted(candidate_id for candidate_id in candidates
                      if candidate_id != selected["id"])
    actual = []
    for index, alternative in enumerate(value):
        row = object_field(alternative, f"decision alternative {index}",
                           {"candidateId", "outcome", "reason"}, set())
        candidate_id = id_field(row["candidateId"], "alternative candidateId")
        candidate = candidates.get(candidate_id)
        if candidate is None or candidate_id == selected["id"]:
            raise VisualPlanContractError("decision alternative is not a distinct candidate")
        if row["outcome"] not in {"lower-ranked", "ineligible", "budget-conflict"}:
            raise VisualPlanContractError("decision alternative outcome is invalid")
        if (candidate["eligibility"] == "eligible") == (row["outcome"] == "ineligible"):
            raise VisualPlanContractError("decision alternative eligibility is inconsistent")
        text_field(row["reason"], "decision alternative reason")
        actual.append(candidate_id)
    if actual != expected:
        raise VisualPlanContractError("decision alternatives must cover every unselected candidate")

"""Evidence-bound visual vocabulary for one selected reference study.

The vocabulary is agent-authored planning research. It preserves inspected
catalog alternatives and their evidence without approving style, quality,
execution, rendering, or verified replication.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from cut_preview_io import bound_json, file_hash
from graphics.catalog_discovery import Catalog
from graphics.reference_reuse_map import (
    _candidate, identifier, pin_file, require, text_field,
)

SCHEMA_VERSION = 1
SCOPE = "reference-style-vocabulary-planning-only"
EVIDENCE_ROLES = frozenset({
    "style-profile", "deep-study", "frame", "motion-sequence", "review",
})
AVAILABILITY = frozenset({"ready", "prerequisite", "research-only"})
MAX_EVIDENCE = 256
MAX_TRAITS = 128
MAX_FAMILIES = 64
MAX_CONTENDERS = 8


def _keys(row: dict, required: set[str], optional: set[str], label: str) -> None:
    """Reject missing or invented contract fields."""
    require(set(row) >= required, f"{label} missing fields: {sorted(required - set(row))}")
    require(set(row) <= required | optional,
            f"{label} has unknown fields: {sorted(set(row) - required - optional)}")


def _text_list(value: object, label: str, maximum: int) -> list[str]:
    """Validate a bounded non-empty list of authored strings."""
    require(isinstance(value, list) and 1 <= len(value) <= maximum,
            f"{label} requires 1..{maximum} entries")
    result = [text_field(item, label) for item in value]
    require(len(set(result)) == len(result), f"{label} contains duplicates")
    return result


def _id_list(value: object, label: str, maximum: int) -> list[str]:
    """Validate a bounded unique identifier list."""
    require(isinstance(value, list) and 1 <= len(value) <= maximum,
            f"{label} requires 1..{maximum} entries")
    result = [identifier(item, label) for item in value]
    require(len(set(result)) == len(result), f"{label} contains duplicates")
    return result


def _evidence(value: object, inputs: dict[str, str]) -> tuple[list[dict], set[str]]:
    """Pin reviewed study and visual evidence with stable citation IDs."""
    require(isinstance(value, list) and 3 <= len(value) <= MAX_EVIDENCE,
            f"evidence requires 3..{MAX_EVIDENCE} records")
    rows, seen, roles = [], set(), set()
    for raw in value:
        require(isinstance(raw, dict), "evidence record must be an object")
        _keys(raw, {"id", "role", "path", "sha256", "observation"}, set(), "evidence")
        evidence_id = identifier(raw["id"], "evidence id")
        require(evidence_id not in seen, f"duplicate evidence id: {evidence_id}")
        require(raw["role"] in EVIDENCE_ROLES, "unknown evidence role")
        pin = pin_file(raw, inputs)
        rows.append({"id": evidence_id, "role": raw["role"], **pin,
                     "observation": text_field(raw["observation"], "evidence observation")})
        seen.add(evidence_id); roles.add(raw["role"])
    require({"style-profile", "deep-study"} <= roles,
            "vocabulary evidence needs style-profile and deep-study records")
    require(bool(roles & {"frame", "motion-sequence", "review"}),
            "vocabulary evidence needs reviewed visual evidence")
    return rows, seen


def _trait(raw: object, evidence_ids: set[str], label: str) -> dict:
    """Validate one evidence-cited characteristic."""
    require(isinstance(raw, dict), f"{label} must be an object")
    _keys(raw, {"id", "description", "evidenceIds"}, set(), label)
    cited = _id_list(raw["evidenceIds"], f"{label} evidence", MAX_EVIDENCE)
    require(set(cited) <= evidence_ids, f"{label} cites unknown evidence")
    return {"id": identifier(raw["id"], f"{label} id"),
            "description": text_field(raw["description"], f"{label} description"),
            "evidenceIds": cited}


def _traits(value: object, evidence_ids: set[str], label: str) -> list[dict]:
    """Validate one bounded trait collection."""
    require(isinstance(value, list) and 1 <= len(value) <= MAX_TRAITS,
            f"{label} requires 1..{MAX_TRAITS} records")
    rows = [_trait(raw, evidence_ids, label) for raw in value]
    ids = [row["id"] for row in rows]
    require(len(set(ids)) == len(ids), f"duplicate {label} id")
    return rows


def _contender(raw: object, evidence_ids: set[str]) -> dict:
    """Validate one inspected alternative and its honest execution status."""
    require(isinstance(raw, dict), "contender must be an object")
    fields = {"catalogRef", "styleFit", "bestFor", "difference", "configuration",
              "variationOptions", "availability", "prerequisites", "evidenceIds", "confidence"}
    _keys(raw, fields, set(), "contender")
    cited = _id_list(raw["evidenceIds"], "contender evidence", MAX_EVIDENCE)
    require(set(cited) <= evidence_ids, "contender cites unknown evidence")
    availability = raw["availability"]
    require(availability in AVAILABILITY, "unknown contender availability")
    prerequisites = raw["prerequisites"]
    require(isinstance(prerequisites, list) and len(prerequisites) <= 32,
            "contender prerequisites must be a bounded list")
    prerequisites = [text_field(item, "contender prerequisite") for item in prerequisites]
    require((availability == "ready") == (not prerequisites),
            "ready contenders need no prerequisites; other statuses need at least one")
    confidence = raw["confidence"]
    require(isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
            and 0 <= confidence <= 1, "contender confidence must be in [0,1]")
    return {"catalogRef": text_field(raw["catalogRef"], "catalog ref"),
            "styleFit": text_field(raw["styleFit"], "contender style fit"),
            "bestFor": text_field(raw["bestFor"], "contender best use"),
            "difference": text_field(raw["difference"], "contender difference"),
            "configuration": text_field(raw["configuration"], "contender configuration"),
            "variationOptions": _text_list(raw["variationOptions"], "variation option", 16),
            "availability": availability, "prerequisites": prerequisites,
            "evidenceIds": cited, "confidence": float(confidence)}


def _family(raw: object, evidence_ids: set[str]) -> dict:
    """Validate one viewer-purpose family and its inspected alternatives."""
    require(isinstance(raw, dict), "family must be an object")
    fields = {"id", "name", "purposes", "sharedStyle", "useWhen", "avoidWhen", "contenders"}
    _keys(raw, fields, set(), "family")
    contenders = raw["contenders"]
    require(isinstance(contenders, list) and 1 <= len(contenders) <= MAX_CONTENDERS,
            f"family requires 1..{MAX_CONTENDERS} contenders")
    contenders = [_contender(row, evidence_ids) for row in contenders]
    refs = [row["catalogRef"] for row in contenders]
    require(len(set(refs)) == len(refs), "family contains a duplicate contender")
    return {"id": identifier(raw["id"], "family id"),
            "name": text_field(raw["name"], "family name"),
            "purposes": _id_list(raw["purposes"], "family purpose", 16),
            "sharedStyle": text_field(raw["sharedStyle"], "family shared style"),
            "useWhen": text_field(raw["useWhen"], "family use guidance"),
            "avoidWhen": text_field(raw["avoidWhen"], "family avoidance guidance"),
            "contenders": contenders}


def _coverage(value: object) -> dict:
    """Require honest inspection coverage and limitations."""
    require(isinstance(value, dict), "coverage must be an object")
    _keys(value, {"status", "reviewed", "limitations"}, set(), "coverage")
    require(value["status"] in {"complete", "limited"}, "coverage status is invalid")
    limitations = value["limitations"]
    require(isinstance(limitations, list) and len(limitations) <= 64,
            "coverage limitations must be a bounded list")
    limitations = [text_field(item, "coverage limitation") for item in limitations]
    require(value["status"] == "complete" or limitations,
            "limited coverage needs at least one limitation")
    return {"status": value["status"],
            "reviewed": text_field(value["reviewed"], "coverage reviewed evidence"),
            "limitations": limitations}


def _selection_policy(value: object) -> dict:
    """Validate the authored rules the strategy agent must apply."""
    require(isinstance(value, dict), "selectionPolicy must be an object")
    fields = {"coherence", "variation", "repetition", "uncertainty"}
    _keys(value, fields, set(), "selectionPolicy")
    return {key: text_field(value[key], f"selection policy {key}") for key in sorted(fields)}


def _authored(value: dict, inputs: dict[str, str]) -> dict:
    """Validate and normalize the agent-authored portion."""
    fields = {"referenceId", "coverage", "evidence", "stableTraits", "flexibleTraits",
              "signatureDevices", "families", "selectionPolicy"}
    _keys(value, fields, set(), "vocabulary draft")
    evidence, evidence_ids = _evidence(value["evidence"], inputs)
    families = value["families"]
    require(isinstance(families, list) and 1 <= len(families) <= MAX_FAMILIES,
            f"vocabulary requires 1..{MAX_FAMILIES} families")
    families = [_family(row, evidence_ids) for row in families]
    ids = [row["id"] for row in families]
    require(len(set(ids)) == len(ids), "duplicate family id")
    return {"referenceId": identifier(value["referenceId"], "reference id"),
            "coverage": _coverage(value["coverage"]), "evidence": evidence,
            "stableTraits": _traits(value["stableTraits"], evidence_ids, "stable trait"),
            "flexibleTraits": _traits(value["flexibleTraits"], evidence_ids, "flexible trait"),
            "signatureDevices": _traits(value["signatureDevices"], evidence_ids, "signature device"),
            "families": families, "selectionPolicy": _selection_policy(value["selectionPolicy"])}


def _candidate_refs(authored: dict) -> list[str]:
    """Return every inspected catalog ref once in stable order."""
    return sorted({row["catalogRef"] for family in authored["families"]
                   for row in family["contenders"]})


def _check_availability(authored: dict, candidates: dict[str, dict]) -> None:
    """Require planning-ready measured sources; job probes remain separate authority."""
    for family in authored["families"]:
        _check_family_availability(family, candidates)


def _check_family_availability(family: dict, candidates: dict[str, dict]) -> None:
    for contender in family["contenders"]:
        candidate = candidates[contender["catalogRef"]]
        eligibility = candidate["record"].get("eligibility") or {}
        required = list(eligibility.get("prerequisites") or [])
        availability = contender["availability"]
        if availability == "ready":
            require(candidate["source"]["exists"],
                    f"ready contender source is unavailable: {contender['catalogRef']}")
            require(eligibility.get("executionStatus") == "measured-compatibility-candidate"
                    and eligibility.get("selectionEligible") is True,
                    f"ready contender lacks measured execution evidence: {contender['catalogRef']}")
        if availability == "prerequisite":
            missing = [item for item in required if item not in contender["prerequisites"]]
            require(not missing,
                    f"contender omits catalog execution prerequisites: {missing}")


def find_style_contender(vocabulary: dict, family_id: str,
                         contender_ref: str) -> dict | None:
    """Return an exact family contender without fuzzy matching."""
    family = next((row for row in vocabulary["families"]
                   if row["id"] == family_id), None)
    if family is None:
        return None
    return next((row for row in family["contenders"]
                 if row["catalogRef"] == contender_ref), None)


def prepare_vocabulary(draft: dict, catalog: Catalog) -> dict:
    """Freeze an authored vocabulary against exact inspected evidence and catalog bytes."""
    inputs: dict[str, str] = {}
    authored = _authored(draft, inputs)
    candidates = {ref: _candidate(catalog, ref, inputs) for ref in _candidate_refs(authored)}
    _check_availability(authored, candidates)
    return {"schemaVersion": SCHEMA_VERSION, "scope": SCOPE, **authored,
            "inputPins": inputs, "candidates": candidates,
            "styleApproved": False, "qualityApproved": False,
            "renderApproved": False, "verifiedMimicQualified": False}


def validate_vocabulary(record: dict, catalog: Catalog) -> dict:
    """Rebuild frozen facts while preserving authored judgments verbatim."""
    generated = {"schemaVersion", "scope", "inputPins", "candidates", "styleApproved",
                 "qualityApproved", "renderApproved", "verifiedMimicQualified"}
    authored_keys = set(record) - generated
    required = {"referenceId", "coverage", "evidence", "stableTraits", "flexibleTraits",
                "signatureDevices", "families", "selectionPolicy"}
    require(authored_keys == required, "vocabulary fields are missing or unknown")
    require(record.get("schemaVersion") == SCHEMA_VERSION and record.get("scope") == SCOPE,
            "invalid vocabulary envelope")
    for field in ("styleApproved", "qualityApproved", "renderApproved",
                  "verifiedMimicQualified"):
        require(record.get(field) is False, f"vocabulary cannot claim {field}")
    expected = prepare_vocabulary({key: deepcopy(record[key]) for key in required}, catalog)
    require(record == expected, "vocabulary evidence or catalog candidates changed; prepare again")
    return {"status": "style-vocabulary-current", "scope": SCOPE,
            "referenceId": expected["referenceId"],
            "coverage": expected["coverage"]["status"],
            "familyCount": len(expected["families"]),
            "contenderCount": len(expected["candidates"]),
            "inputPins": expected["inputPins"], "styleApproved": False,
            "qualityApproved": False, "renderApproved": False,
            "verifiedMimicQualified": False}


def read_checked_vocabulary(file: Path, catalog: Catalog) -> dict[str, Any]:
    """Read and recheck one stable vocabulary artifact."""
    hashed = file_hash(file)
    record = bound_json(file, hashed)
    report = validate_vocabulary(record, catalog)
    require(file_hash(file) == hashed, "style vocabulary changed during validation")
    return {"path": str(file), "sha256": hashed, "record": record,
            "report": report}

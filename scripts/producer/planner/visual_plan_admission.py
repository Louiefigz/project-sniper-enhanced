"""File, catalog, and receipt admission for route-neutral visual plans."""
from __future__ import annotations

import os
from dataclasses import dataclass

from planner.visual_plan_authority_admission import load_catalog_authority
from planner.visual_plan_fields import (
    VisualPlanContractError, canonical_hash, object_field, sha_field,
)
from planner.visual_plan_file_pins import MAX_CATALOG_BYTES, MAX_EVIDENCE_BYTES, verify_file
from planner.visual_plan_receipts import ReceiptRequest, validate_catalog_receipt

_STATUSES = {"integrated-measured", "integrated-unmeasured", "reference",
             "reference-missing-source"}


@dataclass(frozen=True)
class CatalogCandidateRequest:
    """Context shared by catalog and receipt admission."""

    plan: dict
    opportunity: dict
    candidate: dict
    authority: dict
    media_authority: dict
    cache: set[tuple[str, str]]
    receipt_authority: dict | None = None


def _plan_candidates(plan: dict):
    """Yield opportunity/candidate pairs without nesting the admission logic."""
    for opportunity in plan["opportunities"]:
        for candidate in opportunity["candidates"]:
            yield opportunity, candidate


def validate_plan_pins(plan: dict, authority: dict, media_authority: dict,
                       receipt_authority: dict | None = None) -> None:
    """Verify every small evidence pin and every catalog candidate receipt."""
    cache: set[tuple[str, str]] = set()
    for index, pin in enumerate(plan["direction"]["referencePins"]):
        verify_file(pin, f"reference pin {index}", MAX_EVIDENCE_BYTES, cache)
    for opportunity, candidate in _plan_candidates(plan):
        request = CatalogCandidateRequest(
            plan, opportunity, candidate, authority, media_authority,
            cache, receipt_authority)
        _validate_candidate(request)


def _validate_candidate(request: CatalogCandidateRequest) -> None:
    candidate = request.candidate
    _candidate_pins(candidate, request.cache)
    if candidate["modality"] == "catalog":
        _validate_catalog_candidate(request)
        return
    if candidate["eligibility"] == "eligible" \
            and candidate["modality"] in {
                "source-footage", "supplied-broll", "external-media"}:
        _validate_media_candidate(candidate, request.media_authority)
    if candidate["catalogAdmission"] is None:
        return
    raise VisualPlanContractError(
        f"candidate {candidate['id']} has catalog admission outside catalog modality")


def _validate_media_candidate(candidate: dict, authority: dict) -> None:
    source = candidate["source"]
    key = (candidate["modality"], source["recordId"])
    expected = authority.get(key)
    if expected is None:
        raise VisualPlanContractError(
            f"candidate {candidate['id']} source is absent from controller media authority")
    source_sha = source.get("sourceSha256")
    if source["path"] != expected["path"] \
            or source["sha256"] != expected["sourceSha256"] \
            or source_sha != expected["sourceSha256"]:
        raise VisualPlanContractError(
            f"candidate {candidate['id']} source differs from controller media authority")
    if candidate["modality"] == "external-media":
        authorization = candidate["authorization"]
        expected_pin = expected["authorizationEvidence"]
        if expected_pin is None:
            raise VisualPlanContractError(
                f"candidate {candidate['id']} has no controller external-media authorization")
        if not isinstance(authorization, dict) \
                or authorization.get("evidence") != expected_pin:
            raise VisualPlanContractError(
                f"candidate {candidate['id']} authorization differs from controller authority")


def derived_project_route(mode: str, selected: list[dict]) -> str:
    """Derive the only legal whole-project route from selected route classes."""
    if any(row["routeClass"] == "native" for row in selected):
        return "native-short" if mode == "short" else "native-long"
    return "ordinary"


def _candidate_pins(candidate: dict, cache: set[tuple[str, str]]) -> None:
    for index, evidence in enumerate(candidate["evidence"]):
        verify_file(evidence, f"candidate {candidate['id']} evidence {index}",
                    MAX_EVIDENCE_BYTES, cache)
    for index, pin in enumerate(candidate["dependencyPins"]):
        verify_file(pin, f"candidate {candidate['id']} dependency {index}",
                    MAX_EVIDENCE_BYTES, cache)
    authorization = candidate["authorization"]
    if authorization is not None:
        verify_file(authorization["evidence"],
                    f"candidate {candidate['id']} authorization",
                    MAX_EVIDENCE_BYTES, cache)


def _validate_catalog_candidate(request: CatalogCandidateRequest) -> None:
    candidate, authority = request.candidate, request.authority
    source, admission = candidate["source"], candidate["catalogAdmission"]
    if source is None or admission is None:
        raise VisualPlanContractError("catalog candidate lacks source or catalog admission")
    admission = _catalog_admission_shape(admission)
    record = authority["records"].get(source["recordId"])
    if record is None:
        raise VisualPlanContractError("catalog candidate record is absent from pinned index")
    status, record_source = _catalog_facts(record, source["recordId"], authority)
    resource = _resource_row(record, source["recordId"], authority)
    expected = _expected_admission(record, status, resource)
    _compare_admission(admission, expected)
    _verify_catalog_source(source, record_source, record, status)
    _validate_receipts(request, expected, admission)
    _validate_catalog_state(candidate, expected, admission)


def _catalog_admission_shape(value: object) -> dict:
    keys = {"catalogRecordSha256", "executionStatus", "resourceClass",
            "runtimeQualificationRequired", "sourceInspectionEvidence"}
    row = object_field(value, "catalog admission", keys, set())
    sha_field(row["catalogRecordSha256"], "catalog admission record SHA-256")
    if row["executionStatus"] not in _STATUSES:
        raise VisualPlanContractError("catalog admission executionStatus is invalid")
    if row["resourceClass"] not in {"dom-css", "canvas", "gpu-video", "unknown"}:
        raise VisualPlanContractError("catalog admission resourceClass is invalid")
    if type(row["runtimeQualificationRequired"]) is not bool:
        raise VisualPlanContractError(
            "catalog admission runtime qualification requirement is invalid")
    evidence = row["sourceInspectionEvidence"]
    if evidence is not None:
        object_field(evidence, "catalog admission sourceInspectionEvidence",
                     {"path", "sha256"}, set())
    return row


def _compare_admission(admission: dict, expected: dict) -> None:
    for key in ("catalogRecordSha256", "executionStatus", "resourceClass",
                "runtimeQualificationRequired"):
        if admission[key] != expected[key]:
            raise VisualPlanContractError(f"catalog candidate {key} differs from pinned record")


def _catalog_facts(record: dict, record_id: str, authority: dict) -> tuple[str, dict]:
    integration = record.get("integration")
    status = integration.get("status") if isinstance(integration, dict) else "reference"
    if status not in _STATUSES:
        raise VisualPlanContractError(f"catalog record {record_id} status is unsupported")
    source = record.get("source")
    if isinstance(source, dict) and isinstance(source.get("path"), str):
        exists = source.get("exists", os.path.isfile(source["path"]))
        return ("reference-missing-source" if not exists else status), source
    name, kind = record.get("name"), record.get("type")
    if not isinstance(name, str) or kind not in {"block", "component"}:
        raise VisualPlanContractError(f"catalog record {record_id} source is invalid")
    folder = "compositions" if kind == "block" else "compositions/components"
    path = os.path.join(authority["sourceRootPath"], folder, name + ".html")
    return (status if os.path.isfile(path) else "reference-missing-source",
            {"path": path, "exists": os.path.isfile(path)})


def _resource_row(record: dict, record_id: str, authority: dict) -> dict:
    embedded = record.get("resourceEvidence")
    if isinstance(embedded, dict):
        return embedded
    row = authority["resources"].get(record_id)
    if not isinstance(row, dict):
        raise VisualPlanContractError(f"catalog record {record_id} lacks resource evidence")
    return row


def _expected_admission(record: dict, status: str, resource: dict) -> dict:
    resource_class = _resource_class(resource)
    guarded = bool(resource.get("guardedProbeRequired") or status == "reference"
                   or resource_class == "unknown")
    return {"catalogRecordSha256": canonical_hash(record), "executionStatus": status,
            "resourceClass": resource_class,
            "runtimeQualificationRequired": guarded,
            "routeClass": "native" if status.startswith("reference") else "compatibility",
            "record": record}


def _resource_class(resource: dict) -> str:
    if resource.get("webglGpu") is True or resource.get("videoTexture") is True:
        return "gpu-video"
    if resource.get("canvas") is True:
        return "canvas"
    if resource.get("domCss") is True:
        return "dom-css"
    return "unknown"


def _validate_receipts(request: CatalogCandidateRequest, expected: dict,
                       admission: dict) -> None:
    catalog = {key: expected[key] for key in (
        "catalogRecordSha256", "executionStatus", "resourceClass",
        "runtimeQualificationRequired", "routeClass", "record")}
    pin = admission["sourceInspectionEvidence"]
    if pin is None:
        return
    receipt_request = ReceiptRequest(
        "source-inspection", pin, request.plan, request.opportunity,
        request.candidate, catalog, request.receipt_authority)
    validate_catalog_receipt(receipt_request)


def _validate_catalog_state(candidate: dict, expected: dict,
                            admission: dict) -> None:
    status = expected["executionStatus"]
    missing = []
    if status != "reference-missing-source" \
            and admission["sourceInspectionEvidence"] is None:
        missing.append("catalog-static-source-inspection-evidence")
    if status == "integrated-unmeasured":
        missing.append("catalog-integration-unmeasured")
    eligibility = ("blocked" if status == "reference-missing-source" else
                   "prerequisite" if missing else
                   "eligible")
    if candidate["routeClass"] != expected["routeClass"]:
        raise VisualPlanContractError("catalog candidate route differs from pinned record")
    if candidate["eligibility"] != eligibility:
        raise VisualPlanContractError("catalog candidate eligibility differs from pinned evidence")
    if eligibility == "prerequisite" \
            and sorted(candidate["prerequisites"]) != sorted(missing):
        raise VisualPlanContractError("catalog candidate prerequisites differ from pinned evidence")
    if eligibility == "blocked" and "catalog-source-unavailable" not in candidate["exclusionReasons"]:
        raise VisualPlanContractError("blocked catalog candidate lacks source exclusion")


def _verify_catalog_source(source: dict, recorded: dict, record: dict,
                           status: str) -> None:
    if os.path.realpath(source["path"]) != os.path.realpath(recorded["path"]):
        raise VisualPlanContractError("catalog candidate source path differs from pinned record")
    if status == "reference-missing-source":
        return
    verify_file(source, "catalog source", MAX_CATALOG_BYTES)
    if recorded.get("sha256") not in {None, source["sha256"]}:
        raise VisualPlanContractError("catalog source hash differs from pinned record")
    digest = source.get("sourceSha256")
    if digest is not None and digest != source["sha256"]:
        raise VisualPlanContractError("catalog sourceSha256 differs from admitted source bytes")

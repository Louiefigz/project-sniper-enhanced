"""Bounded field validators shared by the visual-plan contract."""
from __future__ import annotations

import hashlib
import re

from cross_runtime_canonical_json import (
    CrossRuntimeCanonicalJsonError,
    canonical_compact_json,
)


class VisualPlanContractError(ValueError):
    """The visual plan is malformed, ambiguous, or exceeds planning bounds."""


MODALITIES = {
    "source-footage", "supplied-broll", "external-media", "catalog", "text",
    "presenter", "custom-native", "omit", "transition",
}
ROUTES = {"ordinary", "native-short", "native-long"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")


def canonical_hash(value: object) -> str:
    """Return a SHA-256 matching the TypeScript compact canonical JSON."""
    try:
        payload = canonical_compact_json(value).encode("utf-8")
    except CrossRuntimeCanonicalJsonError as exc:
        raise VisualPlanContractError("visual plan is not canonical JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def object_field(value: object, name: str, required: set, optional: set) -> dict:
    """Require an object with a closed key set."""
    if not isinstance(value, dict):
        raise VisualPlanContractError(f"{name} must be an object")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        raise VisualPlanContractError(
            f"{name} keys invalid; missing={sorted(missing)}, extra={sorted(extra)}")
    return value


def text_field(value: object, name: str, allow_empty: bool = False) -> str:
    """Require bounded text."""
    if not isinstance(value, str) or len(value) > 4000:
        raise VisualPlanContractError(f"{name} must be bounded text")
    if not allow_empty and not value.strip():
        raise VisualPlanContractError(f"{name} must not be empty")
    return value


def id_field(value: object, name: str) -> str:
    """Require a stable identifier."""
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise VisualPlanContractError(f"{name} must be a stable ID")
    return value


def sha_field(value: object, name: str) -> str:
    """Require a lowercase SHA-256."""
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise VisualPlanContractError(f"{name} must be a lowercase SHA-256")
    return value


def path_field(value: object, name: str) -> str:
    """Require a path reference rather than embedded bytes."""
    path = text_field(value, name)
    if path.startswith("data:") or "\n" in path or "\r" in path:
        raise VisualPlanContractError(f"{name} must reference bytes by path")
    return path


def number_field(value: object, name: str) -> float:
    """Require a zero-to-one score."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VisualPlanContractError(f"{name} must be numeric")
    if not 0 <= value <= 1:
        raise VisualPlanContractError(f"{name} must be between zero and one")
    return float(value)


def strings_field(value: object, name: str, maximum: int = 32) -> list[str]:
    """Require a bounded unique text list."""
    if not isinstance(value, list) or len(value) > maximum:
        raise VisualPlanContractError(f"{name} must be a bounded list")
    rows = [text_field(item, f"{name} item") for item in value]
    if len(rows) != len(set(rows)):
        raise VisualPlanContractError(f"{name} must not contain duplicates")
    return rows


def validate_timing(value: object, name: str, project_end: int) -> dict:
    """Require one half-open window inside the project clock."""
    row = object_field(value, name, {"startFrame", "endFrameExclusive"}, set())
    start, end = row["startFrame"], row["endFrameExclusive"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= project_end:
        raise VisualPlanContractError(f"{name} is outside the project clock")
    return row


def validate_header_fields(plan: dict) -> None:
    """Validate project, catalog, direction, and declared bounds."""
    _validate_project(plan["project"])
    _validate_catalog(plan["catalogPin"])
    _validate_direction(plan["direction"])
    _validate_bounds(plan["bounds"])


def _validate_project(project: object) -> None:
    required = {"mode", "aspect", "durationFrames", "fps", "intentSha256",
                "acceptedProgramSha256", "transcriptSha256"}
    row = object_field(project, "project", required, {"relatedOutputGroup"})
    if row["mode"] not in {"short", "long"} or row["aspect"] not in {"9:16", "16:9", "1:1", "4:5"}:
        raise VisualPlanContractError("project mode or aspect is unsupported")
    if type(row["durationFrames"]) is not int or row["durationFrames"] < 1:
        raise VisualPlanContractError("project durationFrames must be positive")
    fps = object_field(row["fps"], "project fps", {"numerator", "denominator"}, set())
    if any(type(fps[key]) is not int or fps[key] < 1 for key in fps):
        raise VisualPlanContractError("project fps must be a positive rational")
    for key in ("intentSha256", "acceptedProgramSha256", "transcriptSha256"):
        sha_field(row[key], f"project {key}")
    if "relatedOutputGroup" in row:
        id_field(row["relatedOutputGroup"], "project relatedOutputGroup")


def _validate_catalog(pin: object) -> None:
    path_keys = {"registryPath", "snapshotIndexPath", "snapshotLockPath",
                 "snapshotResourcePath", "capabilityPath", "studyPath",
                 "indexPath", "resourceIndexPath", "sourceRootPath"}
    sha_keys = {"registrySha256", "snapshotIndexSha256", "snapshotLockSha256",
                "snapshotResourceSha256", "capabilitySha256", "studySha256",
                "indexSha256", "resourceIndexSha256", "sourceSetSha256"}
    keys = {"catalogId", "version"} | path_keys | sha_keys
    row = object_field(pin, "catalogPin", keys, set())
    id_field(row["catalogId"], "catalogPin catalogId")
    text_field(row["version"], "catalogPin version")
    for key in path_keys:
        path_field(row[key], f"catalogPin {key}")
    for key in sha_keys:
        sha_field(row[key], f"catalogPin {key}")


def _validate_direction(direction: object) -> None:
    required = {"rationale", "palette", "typography", "motionFamily",
                "transitionFamily", "density", "repetition", "referencePins",
                "unresolvedAmbiguity"}
    row = object_field(direction, "direction", required, set())
    for key in ("rationale", "motionFamily", "transitionFamily"):
        text_field(row[key], f"direction {key}")
    for key in ("palette", "typography", "unresolvedAmbiguity"):
        strings_field(row[key], f"direction {key}")
    density = object_field(row["density"], "direction density",
                           {"maxVisualsPerSection", "minBreathingFrames"}, set())
    repetition = object_field(row["repetition"], "direction repetition",
                              {"maxConsecutiveFamily", "maxIdenticalDevelopment"}, set())
    if any(type(value) is not int or value < 0 for value in density.values()):
        raise VisualPlanContractError("direction density values must be nonnegative integers")
    if any(type(value) is not int or value < 1 for value in repetition.values()):
        raise VisualPlanContractError("direction repetition values must be positive integers")
    if not isinstance(row["referencePins"], list) or len(row["referencePins"]) > 16:
        raise VisualPlanContractError("direction referencePins must be bounded")
    for pin in row["referencePins"]:
        item = object_field(pin, "reference pin", {"id", "path", "sha256"}, set())
        id_field(item["id"], "reference pin id")
        path_field(item["path"], "reference pin path")
        sha_field(item["sha256"], "reference pin sha256")


def _validate_bounds(bounds: object) -> None:
    keys = {"maxOpportunities", "maxCandidatesPerOpportunity",
            "maxEvidencePerCandidate", "allocatorBeamWidth"}
    row = object_field(bounds, "bounds", keys, set())
    limits = {"maxOpportunities": 256, "maxCandidatesPerOpportunity": 5,
              "maxEvidencePerCandidate": 8, "allocatorBeamWidth": 64}
    for key, maximum in limits.items():
        if type(row[key]) is not int or not 1 <= row[key] <= maximum:
            raise VisualPlanContractError(f"bounds {key} is outside its limit")


def validate_candidate(candidate: object, name: str, bounds: dict) -> dict:
    """Validate one bounded, path-only candidate record."""
    required = {"id", "modality", "eligibility", "routeClass", "source",
                "catalogAdmission", "composition", "evidence", "dependencyPins", "authorization",
                "scores", "adaptationEstimate",
                "prerequisites", "exclusionReasons", "decisionReason", "confidence",
                "unresolvedAmbiguity", "limitations", "expectedVisibleResult", "reviewTarget"}
    row = object_field(candidate, name, required, {"repeatIntent"})
    id_field(row["id"], f"{name} id")
    if row["modality"] not in MODALITIES or row["eligibility"] not in {"eligible", "prerequisite", "blocked"}:
        raise VisualPlanContractError(f"{name} modality or eligibility is invalid")
    if row["routeClass"] not in {"compatibility", "native", "no-render"}:
        raise VisualPlanContractError(f"{name} routeClass is invalid")
    if row["adaptationEstimate"] not in {"none", "small", "medium", "large", "unknown"}:
        raise VisualPlanContractError(f"{name} adaptationEstimate is invalid")
    restrained = row["modality"] in {"presenter", "omit"}
    if (row["routeClass"] == "no-render") != restrained:
        raise VisualPlanContractError(f"{name} no-render route is inconsistent")
    if row["source"] is not None:
        _validate_source(row["source"], f"{name} source")
    source_modalities = {"catalog", "source-footage", "supplied-broll", "external-media"}
    if row["modality"] in source_modalities and row["source"] is None:
        raise VisualPlanContractError(f"{name} selected modality requires a source reference")
    if row["modality"] == "external-media" \
            and row["eligibility"] == "eligible" and row["authorization"] is None:
        raise VisualPlanContractError(f"{name} external media needs authorization")
    if row["eligibility"] == "eligible":
        if row["prerequisites"] or row["exclusionReasons"]:
            raise VisualPlanContractError(f"{name} eligible candidate retains blockers")
        if any(item.get("status") == "unavailable" for item in row["evidence"]
               if isinstance(item, dict)):
            raise VisualPlanContractError(f"{name} eligible candidate has unavailable evidence")
    _validate_candidate_details(row, name, bounds)
    return row


def _validate_source(source: object, name: str) -> None:
    row = object_field(source, name, {"recordId", "path", "sha256"},
                       {"sourceSha256", "range"})
    id_field(row["recordId"], f"{name} recordId")
    path_field(row["path"], f"{name} path")
    sha_field(row["sha256"], f"{name} sha256")
    if "sourceSha256" in row:
        sha_field(row["sourceSha256"], f"{name} sourceSha256")
    if "range" in row:
        validate_timing(row["range"], f"{name} range", 1000000000)


def _validate_candidate_details(row: dict, name: str, bounds: dict) -> None:
    composition = object_field(row["composition"], f"{name} composition",
                               {"familyId", "anatomy", "development", "motionFamily"}, set())
    id_field(composition["familyId"], f"{name} familyId")
    for key in ("anatomy", "development", "motionFamily"):
        text_field(composition[key], f"{name} {key}")
    if not isinstance(row["evidence"], list) or len(row["evidence"]) > bounds["maxEvidencePerCandidate"]:
        raise VisualPlanContractError(f"{name} evidence exceeds the declared bound")
    for index, evidence in enumerate(row["evidence"]):
        _validate_evidence(evidence, f"{name} evidence {index}")
    if not isinstance(row["dependencyPins"], list) or len(row["dependencyPins"]) > 16:
        raise VisualPlanContractError(f"{name} dependencyPins must be bounded")
    for index, pin in enumerate(row["dependencyPins"]):
        _validate_pin(pin, f"{name} dependency pin {index}")
    if row["authorization"] is not None:
        authorization = object_field(row["authorization"], f"{name} authorization",
                                     {"basis", "evidence"}, set())
        text_field(authorization["basis"], f"{name} authorization basis")
        _validate_pin(authorization["evidence"], f"{name} authorization evidence")
    scores = object_field(row["scores"], f"{name} scores",
                          {"validity", "semanticFit", "readability", "feasibility",
                           "coherence", "variation", "recentReusePenalty"}, set())
    for key, value in scores.items():
        number_field(value, f"{name} score {key}")
    for key in ("prerequisites", "exclusionReasons", "unresolvedAmbiguity", "limitations"):
        strings_field(row[key], f"{name} {key}")
    if not row["evidence"] and not row["limitations"]:
        raise VisualPlanContractError(
            f"{name} needs inspected evidence or an explicit limitation")
    for key in ("decisionReason", "expectedVisibleResult", "reviewTarget"):
        text_field(row[key], f"{name} {key}")
    number_field(row["confidence"], f"{name} confidence")
    if "repeatIntent" in row:
        _validate_repeat(row["repeatIntent"], name)


def _validate_evidence(value: object, name: str) -> None:
    keys = {"id", "kind", "path", "sha256", "status", "observation"}
    item = object_field(value, name, keys, set())
    id_field(item["id"], f"{name} id")
    path_field(item["path"], f"{name} path")
    sha_field(item["sha256"], f"{name} sha256")
    text_field(item["observation"], f"{name} observation")
    kinds = {"catalog-record", "source-range", "preview", "motion-inspection",
             "reference-family", "attachment"}
    if item["kind"] not in kinds or item["status"] not in {"inspected", "limited", "unavailable"}:
        raise VisualPlanContractError(f"{name} kind or status is invalid")


def _validate_pin(value: object, name: str) -> None:
    pin = object_field(value, name, {"path", "sha256"}, set())
    path_field(pin["path"], f"{name} path")
    sha_field(pin["sha256"], f"{name} sha256")


def _validate_repeat(value: object, name: str) -> None:
    repeat = object_field(value, f"{name} repeatIntent",
                          {"classification", "reason", "priorOpportunityId",
                           "priorCandidateId"}, set())
    if repeat["classification"] not in {"signature", "callback", "necessary"}:
        raise VisualPlanContractError(f"{name} repeat classification is invalid")
    text_field(repeat["reason"], f"{name} repeat reason")
    id_field(repeat["priorOpportunityId"], f"{name} prior opportunity")
    id_field(repeat["priorCandidateId"], f"{name} prior candidate")

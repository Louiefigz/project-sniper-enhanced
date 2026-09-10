"""Closed server-owned private opening inputs, separate from any approval gate.

The caller must authenticate the durable job, accepted cut, readiness and lease.
Self-hashing JSON cannot provide that authentication. This worker rechecks the
exact supplied document bytes and their internal media/timeline relationships.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
from uuid import UUID

from cut_preview_authority import request_value
from cut_preview_io import digest, file_hash, read_bytes
from edit.compatibility_projection import build_projection
from ingest_execution_authority import execution_media_authority_entries
from headless.external_media_verification import SourceVerificationRuntime, check_verification_clock
from ingest_media_observation import SourceVerificationCapture, VerifiedExecutionMedia
from guided_presenter_intake import (current_opening_profile, current_profile_for_inputs,
                                     current_manual_profile, manual_preserved_fields)
from guided_proposal_reframe import validate_requested_manual_crop
from guided_proposal_music import validate_requested_music, verify_music_admission
from guided_proposal_presenter import validate_requested_presenter

PROFILE = "unity-source-float-own-screen-v1"
DOCUMENTS = {"authority", "acceptedPlan", "cutRequest", "pictureLock", "cutProjection", "timelineMap",
    "readinessReceipt", "readinessPacket", "readinessBundle", "treatmentDraft", "candidatePlan", "manifest",
    "frameBindings", "occurrences"}
_INPUT_KEYS = {"schemaVersion", "kind", "executionId", "executionInputHash", "profile", "documents", "pipeline"}


@dataclass(frozen=True)
class OpeningInputs:
    """Exact server invocation, held bytes and currently validated documents."""

    path: Path
    sha256: str
    value: dict
    documents: dict
    verified_media: VerifiedExecutionMedia | None = field(default=None, compare=False, repr=False)


def closed(value: object, keys: set[str], label: str) -> dict:
    """No defaulting unknown or omitted contract fields."""
    if type(value) is not dict or set(value) != keys:
        raise RuntimeError(f"opening {label} is not its closed contract")
    return value


def hash_value(value: object) -> str:
    """Require actual lowercase SHA identity, not truthy metadata."""
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RuntimeError("opening identity is not a SHA-256")
    return value


def _json(path: Path, expected: str, maximum: int) -> tuple[dict, int]:
    """Parse only the same bounded, no-follow bytes whose held SHA was checked."""
    raw = read_bytes(path, maximum)
    if hashlib.sha256(raw).hexdigest() != hash_value(expected):
        raise RuntimeError("opening document bytes differ from held identity")
    value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict:
        raise RuntimeError("opening document is not an object")
    return value, len(raw)


def _document(ref: object, maximum: int) -> tuple[dict, int]:
    """Read one canonical bounded regular file with its separately supplied SHA."""
    row = closed(ref, {"path", "sha256"}, "document reference")
    if type(row["path"]) is not str:
        raise RuntimeError("opening document path is missing")
    path = Path(row["path"])
    raw = row["path"]
    if not path.is_absolute() or str(path) != raw or "\\" in raw or any(ord(char) < 32 for char in raw) \
            or any(part in {"", ".", ".."} for part in raw.split("/")[1:]) or path.resolve(strict=True) != path:
        raise RuntimeError("opening document path is not canonical")
    return _json(path, row["sha256"], maximum)


def _documents(refs: dict) -> dict:
    """Retain the server's per-document and whole-input allocation ceilings."""
    result, remaining = {}, 64 * 1024 * 1024
    for name, ref in refs.items():
        value, size = _document(ref, min(16 * 1024 * 1024, remaining))
        result[name] = value
        remaining -= size
    return result


def _same(actual: object, expected: object, label: str) -> None:
    """Use exact cross-runtime JSON equality instead of Python bool/int coercion."""
    if digest(actual) != digest(expected):
        raise RuntimeError(f"opening {label} changed")


# Guided V4 authors exactly these two style keys onto the accepted target; every
# other target field (geometry, mode, scope, lanes, excerpt) must stay locked.
# Mirrors src/lib/server/guided-opening-media-input.ts styleFreeTarget.
STYLE_ONLY_TARGET_KEYS = ("graphicsStyle", "graphicsStyleRationale")


def style_free_target(target: object) -> object:
    """The candidate target with V4's style-only keys removed, for the locked comparison."""
    if not isinstance(target, dict):
        return target
    return {key: value for key, value in target.items() if key not in STYLE_ONLY_TARGET_KEYS}


def _cut(inputs: OpeningInputs) -> dict | None:
    """Reuse the accepted cut compiler, including its quantized semantic timeline hash."""
    docs, refs = inputs.documents, inputs.value["documents"]
    request = request_value(docs["cutRequest"])
    lock, accepted = docs["pictureLock"], docs["acceptedPlan"]
    for name, key in (("acceptedPlan", "planHash"), ("pictureLock", "pictureLockHash"),
                      ("cutProjection", "projectionReceiptHash")):
        _same(refs[name]["sha256"], request[key], key)
    for key in ("cutAuthorityDigest", "cutApprovalReceiptHash", "cutReviewApprovalReceiptHash",
                "timelineMapHash", "projectionReceiptHash"):
        _same(lock.get(key), request[key], key)
    projection = build_projection(accepted, lock["approvedCutPlanHash"])
    _same(docs["cutProjection"], projection, "accepted projection")
    _same(docs["timelineMap"], projection["timelineMap"], "actual timeline document")
    _same(projection["timelineMapHash"], request["timelineMapHash"], "timeline semantic hash")
    _same(lock["manifestHash"], refs["manifest"]["sha256"], "accepted source manifest")
    for key in ("cutTrack", "cutDecisions"):
        _same(docs["candidatePlan"].get(key), accepted.get(key), f"locked {key}")
    presenter = validate_requested_presenter(accepted, docs["candidatePlan"], docs["readinessPacket"], docs.get("manifest", {}))
    # Local prior-lane validation only: held docs/candidate and all later hashes remain actual V8.
    packet = presenter.prior_packet if presenter is not None else docs["readinessPacket"]
    if presenter is None:
        _same(style_free_target(docs["candidatePlan"].get("target")), accepted.get("target"), "locked target")
    requested_crop = validate_requested_manual_crop(accepted, docs["candidatePlan"],
        packet, inputs.value.get("profile"))
    if current_manual_profile(inputs.value.get("profile")) and not requested_crop:
        for key in manual_preserved_fields(inputs.value["profile"]):
            _same(docs["candidatePlan"].get(key), accepted.get(key), f"submitted manual short {key}")
    return validate_requested_music(accepted, docs["candidatePlan"], packet, docs.get("manifest", {}))


def _readiness(inputs: OpeningInputs) -> None:
    """Bind actual server-verified readiness/draft, without granting render approval."""
    docs, authority = inputs.documents, inputs.documents["authority"]
    receipt, packet, bundle = (docs[name] for name in ("readinessReceipt", "readinessPacket", "readinessBundle"))
    expected = {"readinessHash": digest(receipt), "proposalHash": packet["proposalHash"],
        "draftRevisionHash": digest(docs["treatmentDraft"]), "clockHash": packet["clockHash"],
        "generationStartedAt": packet["generationStartedAt"], "cutDecisionHash": packet["cutDecisionHash"],
        "acceptedRevisionHash": packet["parentRevisionHash"], "rawAdmissionHash": packet["treatmentAdmissionHash"]}
    for key, value in expected.items():
        _same(authority[key], value, key)
    for key, value in (("packetHash", digest(packet)), ("reviewBundleHash", digest(bundle)),
                       ("treatmentDraftRevisionHash", digest(docs["treatmentDraft"]))):
        _same(receipt[key], value, key)
    if receipt.get("kind") != "guided-proposal-readiness" or receipt.get("executable") is not False \
            or bundle.get("verdict") != "clean" or bundle.get("executable") is not False:
        raise RuntimeError("opening needs actual non-executable clean proposal readiness")
    _same(packet["candidate"], docs["candidatePlan"], "reviewed candidate")
    _same(packet["evidence"]["frameRate"], authority["frameRate"], "reviewed frame clock")
    _same(packet["evidence"]["totalFrames"], authority["totalFrames"], "reviewed frame count")
    _same(packet["executionBindings"], docs["frameBindings"], "reviewed frame bindings")
    _same(packet["range"]["approval"], authority["core"], "reviewed opening core")
    _same(packet["range"]["review"], authority["review"], "reviewed opening context")
    occurrence = {key: packet["evidence"][key] for key in ("anchors", "occurrences", "segments")}
    _same(occurrence, docs["occurrences"], "whole occurrence projection")
    draft = docs["treatmentDraft"]
    if draft.get("workflowState") != "TREATMENT_DRAFT" or draft.get("schemaVersion") != 2:
        raise RuntimeError("opening requires an isolated treatment draft, not a final revision")
    _same(draft["planObjectHash"], digest(docs["candidatePlan"]), "draft plan")
    _same(draft["parentRevisionHash"], authority["acceptedRevisionHash"], "draft accepted parent")


def _authority(inputs: OpeningInputs) -> None:
    """The private execution authority cannot be a relabelled unavailable adapter."""
    docs, refs = inputs.documents, inputs.value["documents"]
    value, request = docs["authority"], docs["cutRequest"]
    keys = {"schemaVersion", "kind", "scope", "profile", "runId", "previewAttempt", "contextHash",
        "cutDecisionHash", "acceptedRevisionHash", "requestHash", "pictureLockHash", "projectionHash",
        "sourceSetDigest", "manifestHash", "timelineMapHash", "rawAdmissionHash", "proposalHash", "readinessHash",
        "draftRevisionHash", "candidatePlanHash", "frameBindingsHash", "occurrenceEvidenceHash", "clockHash",
        "generationStartedAt", "frameRate", "totalFrames", "target", "core", "review"}
    closed(value, keys, "media authority")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 2 \
            or value["kind"] != "guided-opening-media-authority" or value["profile"] != current_opening_profile(inputs.value["profile"]) \
            or value["scope"] != "private-opening-execution-not-opening-approval-body-or-delivery":
        raise RuntimeError("opening media authority role is unsupported")
    expected = {"profile": current_profile_for_inputs(inputs),
        "requestHash": request["requestHash"], "pictureLockHash": request["pictureLockHash"],
        "projectionHash": request["projectionReceiptHash"], "timelineMapHash": request["timelineMapHash"],
        "manifestHash": refs["manifest"]["sha256"], "candidatePlanHash": digest(docs["candidatePlan"]),
        "frameBindingsHash": digest(docs["frameBindings"]), "occurrenceEvidenceHash": digest(docs["occurrences"]),
        "sourceSetDigest": docs["manifest"]["sourceSetAdmission"]["sourceSetDigest"]}
    for key, item in expected.items():
        _same(value[key], item, key)
    _same(value["target"], style_free_target(docs["candidatePlan"]["target"]), "accepted target")


def observe_inputs(inputs: OpeningInputs, capture: SourceVerificationCapture | None = None) -> list[dict]:
    """Recheck all exact docs and all admitted source bytes, including silent/unused rows."""
    if file_hash(inputs.path) != inputs.sha256:
        raise RuntimeError("opening invocation bytes changed")
    current = _documents(inputs.value["documents"])
    _same(current, inputs.documents, "held documents")
    music = _cut(inputs)
    _authority(inputs)
    _readiness(inputs)
    args = current["candidatePlan"], current["manifest"], inputs.value["documents"]["manifest"]["path"]
    entries = execution_media_authority_entries(*args) if capture is None else execution_media_authority_entries(*args, capture)
    if not entries:
        raise RuntimeError("opening requires current admitted source bytes")
    verify_music_admission(music, entries)
    return entries


def read_inputs(path: Path, expected_sha: str) -> OpeningInputs:
    """Historical class only; never relabel an old invocation or result."""
    value = closed(_json(path, expected_sha, 128 * 1024)[0], _INPUT_KEYS, "invocation")
    return _read_input_value(path, expected_sha, value, (PROFILE, None))


def read_current_inputs(path: Path, expected_sha: str,
                        verification_runtime: SourceVerificationRuntime | None = None) -> OpeningInputs:
    """Dispatch explicit current classes with the same exact document authority."""
    check_verification_clock(verification_runtime)
    value = closed(_json(path, expected_sha, 128 * 1024)[0], _INPUT_KEYS, "invocation")
    return _read_input_value(path, expected_sha, value, (current_opening_profile(value["profile"]), verification_runtime))


def _read_input_value(path: Path, expected_sha: str, value: dict,
                      policy: tuple[str, SourceVerificationRuntime | None]) -> OpeningInputs:
    """Shared bounded shape validation does not change the selected class."""
    profile, runtime = policy
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 \
            or value["kind"] != "guided-opening-media-input" or value["profile"] != profile:
        raise RuntimeError("opening media input is unsupported")
    if type(value["executionId"]) is not str or str(UUID(value["executionId"])) != value["executionId"]:
        raise RuntimeError("opening execution id is malformed")
    _same(hash_value(value["executionInputHash"]), digest({key: item for key, item in value.items()
                                                          if key != "executionInputHash"}), "execution input hash")
    refs = closed(value["documents"], DOCUMENTS, "document set")
    documents = _documents(refs)
    result = OpeningInputs(path, expected_sha, value, documents)
    return _initial_observation(result, runtime)


def _initial_observation(inputs: OpeningInputs, runtime: SourceVerificationRuntime | None) -> OpeningInputs:
    """Keep the original successful source read without any extra hash or JSON fields."""
    if runtime is None:
        observe_inputs(inputs)
        return inputs
    capture = SourceVerificationCapture(runtime)
    try:
        entries = observe_inputs(inputs, capture)
        return replace(inputs, verified_media=capture.finish(entries))
    except BaseException:
        capture.abort()
        raise

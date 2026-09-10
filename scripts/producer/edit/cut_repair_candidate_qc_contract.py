"""Closed full-plan candidate authority for cut-repair QC."""
from __future__ import annotations

import os
from dataclasses import replace

from edit.cut_repair_candidate_qc_target import dirty_window, target_phrase
from edit.cut_repair_candidate_qc_types import (
    CandidateAuthority,
    CandidateQcContractError,
)
from edit.cut_repair_context_sources import (
    digest,
    require_hash,
    require_keys,
    stable_file_digest,
    stable_json,
)

_PACKAGE_KEYS = {
    "schemaVersion", "kind", "status", "idempotencyKey",
    "targetDirectiveHash", "contextAuthorityHash", "contextObjectHash",
    "analysisObjectHash", "parentRevisionHash", "proposedReviewAction",
    "reviewProjectionHash", "renderInvalidationStrategy", "fragmentReceipt",
    "compositeReceipt", "fragmentMediaSha256", "compositeMediaSha256",
    "reviewRenderGraphReceiptHash",
    "reviewRenderGraphCandidatePointerHash", "reviewCandidateMediaSha256",
    "reviewCandidatePath", "reviewCandidateDescriptorHash",
    "reviewCandidateDescriptorPath", "previousRenderGraphHash",
    "previousRenderGraphReceiptHash", "blockingRequirements", "preparedAt",
}
_DESCRIPTOR_KEYS = {
    "schemaVersion", "kind", "status", "operationHash",
    "reviewPlanObjectHash", "reviewPlanContentHash",
    "reviewTimelineMapHash", "reviewRenderGraphHash",
    "reviewRenderGraphReceiptHash",
    "reviewRenderGraphCandidatePointerHash", "candidatePath",
    "candidateSha256",
}
def _canonical_producer(producer: str) -> str:
    lexical = os.path.abspath(producer)
    if lexical != producer or os.path.realpath(lexical) != lexical \
            or not os.path.isdir(lexical) or os.path.islink(lexical):
        raise CandidateQcContractError(
            "producer directory must be canonical and real")
    return lexical


def _inside(path: object, root: str, label: str) -> str:
    if not isinstance(path, str) or os.path.abspath(path) != path:
        raise CandidateQcContractError(f"{label} path is not absolute")
    resolved = os.path.realpath(path)
    if resolved != path or os.path.islink(path) \
            or os.path.commonpath([root, resolved]) != root:
        raise CandidateQcContractError(f"{label} escapes its authority root")
    return resolved


def _object_path(producer: str, family: str, value_hash: str) -> str:
    require_hash(value_hash, f"{family} object hash")
    return os.path.join(
        producer, ".sniper-authority-v1", "objects", family,
        f"{value_hash}.json")


def _authority_object(
    producer: str,
    family: str,
    value_hash: str,
    label: str,
) -> dict:
    path = _object_path(producer, family, value_hash)
    value, observed = stable_json(path, label)
    if observed != value_hash:
        raise CandidateQcContractError(f"{label} object digest is stale")
    return value


def _prepared_package(producer: str, preparation_hash: str) -> dict:
    package = _authority_object(
        producer, "cut-repairs", preparation_hash, "preparation package")
    require_keys(package, _PACKAGE_KEYS, _PACKAGE_KEYS, "preparation package")
    expected = (
        package.get("schemaVersion"), package.get("kind"),
        package.get("status"))
    if expected != (
            1, "cut-repair-preparation-package",
            "rendered-plan-candidate-prepared"):
        raise CandidateQcContractError("preparation package type is unsupported")
    return package


def _operation(package: dict) -> dict:
    action = package.get("proposedReviewAction")
    if not isinstance(action, dict) or not isinstance(
            action.get("operation"), dict):
        raise CandidateQcContractError("preparation action is malformed")
    operation = action["operation"]
    operation_hash = require_hash(
        action.get("operationHash"), "preparation operation hash")
    if operation.get("schemaVersion") != 1 \
            or operation.get("operation") != "cut.restoreSpeech" \
            or digest(operation) != operation_hash:
        raise CandidateQcContractError("preparation operation is stale")
    return operation


def _descriptor(producer: str, package: dict) -> dict:
    expected_hash = require_hash(
        package.get("reviewCandidateDescriptorHash"),
        "candidate descriptor hash")
    stored = _authority_object(
        producer, "cut-repairs", expected_hash, "candidate descriptor")
    require_keys(stored, _DESCRIPTOR_KEYS, _DESCRIPTOR_KEYS,
                 "candidate descriptor")
    staging = os.path.join(producer, ".sniper-cut-repair-staging")
    staged_path = _inside(
        package.get("reviewCandidateDescriptorPath"), staging,
        "candidate descriptor")
    staged, observed = stable_json(staged_path, "staged candidate descriptor")
    if observed != expected_hash or staged != stored:
        raise CandidateQcContractError(
            "staged candidate descriptor was substituted")
    return stored


def _bind_descriptor(package: dict, descriptor: dict, operation: dict) -> None:
    action = package["proposedReviewAction"]
    pairs = {
        "operationHash": action["operationHash"],
        "reviewPlanObjectHash": action["reviewPlanObjectHash"],
        "reviewPlanContentHash": action["reviewPlanContentHash"],
        "reviewTimelineMapHash": action["reviewTimelineMapHash"],
        "reviewRenderGraphHash": action["reviewRenderGraphHash"],
        "reviewRenderGraphReceiptHash":
            package["reviewRenderGraphReceiptHash"],
        "reviewRenderGraphCandidatePointerHash":
            package["reviewRenderGraphCandidatePointerHash"],
        "candidatePath": package["reviewCandidatePath"],
        "candidateSha256": package["reviewCandidateMediaSha256"],
    }
    expected = (1, "cut-repair-rendered-plan-candidate", "candidate-proved")
    observed = (
        descriptor.get("schemaVersion"), descriptor.get("kind"),
        descriptor.get("status"))
    if observed != expected or any(
            descriptor.get(key) != value for key, value in pairs.items()) \
            or digest(operation) != descriptor.get("operationHash"):
        raise CandidateQcContractError(
            "rendered candidate does not bind the preparation package")


def _context(producer: str, package: dict) -> dict:
    context_hash = require_hash(
        package.get("contextObjectHash"), "preparation context object")
    context = _authority_object(
        producer, "cut-repairs", context_hash, "cut repair context")
    supplied = require_hash(
        context.get("authorityHash"), "cut repair context authority")
    core = {key: value for key, value in context.items()
            if key != "authorityHash"}
    if supplied != package.get("contextAuthorityHash") \
            or digest(core) != supplied:
        raise CandidateQcContractError("cut repair context authority is stale")
    return context


def reopen_candidate_context(authority: CandidateAuthority) -> dict:
    """Reobserve the exact context object bound to a candidate authority."""
    return _context(authority.producer, authority.package)


def _source_alignment(context: dict, operation: dict) -> tuple:
    """Reopen the admitted source and bind its transcript-owned sample span."""
    media = context.get("sourceMedia")
    target = operation.get("target")
    if not isinstance(media, dict) or not isinstance(target, dict):
        raise CandidateQcContractError(
            "source-waveform alignment authority is absent")
    keys = {"sourceId", "path", "sha256"}
    require_keys(media, keys, keys, "source media alignment authority")
    source_id = media.get("sourceId")
    path = media.get("path")
    expected_hash = require_hash(
        media.get("sha256"), "alignment source media hash")
    if not isinstance(source_id, str) or not source_id \
            or target.get("sourceId") != source_id \
            or context.get("transcript", {}).get("sourceId") != source_id \
            or not isinstance(path, str):
        raise CandidateQcContractError(
            "source-waveform identity does not match the repair target")
    if stable_file_digest(path, "alignment source media") != expected_hash:
        raise CandidateQcContractError(
            "alignment source media bytes are stale")
    sample_range = target.get("sourceSampleRange")
    if not isinstance(sample_range, dict):
        raise CandidateQcContractError("alignment source span is absent")
    start = sample_range.get("startSample")
    end = sample_range.get("endSampleExclusive")
    rate = operation.get("sourceSampleRate")
    if any(type(value) is not int for value in (start, end, rate)) \
            or start < 0 or end <= start or rate <= 0:
        raise CandidateQcContractError(
            "alignment source sample authority is malformed")
    return path, expected_hash, source_id, start, end, rate


def load_candidate_authority_base(
    producer: str, preparation_hash: str,
) -> CandidateAuthority:
    """Reopen the prepared candidate before alternate-take selection."""
    producer = _canonical_producer(producer)
    package = _prepared_package(producer, preparation_hash)
    operation = _operation(package)
    descriptor = _descriptor(producer, package)
    _bind_descriptor(package, descriptor, operation)
    staging = os.path.join(producer, ".sniper-cut-repair-staging")
    candidate_path = _inside(
        descriptor.get("candidatePath"), staging, "full-plan candidate")
    candidate_hash = require_hash(
        descriptor.get("candidateSha256"), "full-plan candidate hash")
    if stable_file_digest(candidate_path, "full-plan candidate") \
            != candidate_hash:
        raise CandidateQcContractError("full-plan candidate bytes are stale")
    context = _context(producer, package)
    phrase, word_ids = target_phrase(context, operation)
    picture = operation.get("pictureDirtyWindows")
    if not isinstance(picture, list):
        raise CandidateQcContractError("picture dirty windows are malformed")
    source = _source_alignment(context, operation)
    total_frames = context.get("totalFrames")
    if type(total_frames) is not int or total_frames <= 0:
        raise CandidateQcContractError(
            "candidate program frame count is absent")
    return CandidateAuthority(
        producer=producer,
        preparation_hash=preparation_hash,
        package=package,
        descriptor=descriptor,
        candidate_path=candidate_path,
        candidate_sha256=candidate_hash,
        operation=operation,
        target_phrase=phrase,
        target_word_ids=word_ids,
        source_media_path=source[0],
        source_media_sha256=source[1],
        source_id=source[2],
        source_start_sample=source[3],
        source_end_sample_exclusive=source[4],
        source_sample_rate=source[5],
        total_frames=total_frames,
        window=dirty_window(context, operation),
        picture_dirty=bool(picture),
        alternate_take_selection=None,
        alternate_take_selection_hash=None,
        alternate_take_selection_path=None,
    )


def load_candidate_authority(
    producer: str,
    preparation_hash: str,
) -> CandidateAuthority:
    """Require selection authority before any picture-dirty QC tool runs."""
    authority = load_candidate_authority_base(producer, preparation_hash)
    if not authority.picture_dirty:
        return authority
    from edit.alternate_take_authority import load_alternate_take_selection
    selection, selection_hash, selection_path = (
        load_alternate_take_selection(authority))
    return replace(
        authority,
        alternate_take_selection=selection,
        alternate_take_selection_hash=selection_hash,
        alternate_take_selection_path=selection_path,
    )

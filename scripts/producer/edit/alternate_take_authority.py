"""Immutable selection receipts for picture-changing alternate takes."""
from __future__ import annotations

import os
import stat

from contracts.schema_validator import (
    SchemaValidationError,
    validate_document,
)
from edit.alternate_take_candidates import alternate_take_output_range
from edit.alternate_take_derivation import (
    validate_alternate_take_candidate_set,
)
from edit.alternate_take_types import AlternateTakeAuthorityError
from edit.alternate_take_selection import (
    AlternateTakeDecision,
    released_selection_policy,
    select_candidate,
)
from edit.cut_repair_candidate_qc_store import publish_json
from edit.cut_repair_candidate_qc_types import CandidateAuthority
from edit.cut_repair_context_sources import (
    ContextMaterializationError,
    digest,
    require_hash,
    stable_json,
)
from edit.exact_timing import PositiveRational, TimingContractError

_SCHEMA = "cut-repair-alternate-take-selection-v1.schema.json"
_RECEIPT_NAME = "alternate-take-selection.json"


def _context(authority: CandidateAuthority) -> dict:
    from edit.cut_repair_candidate_qc_contract import (
        reopen_candidate_context,
    )
    context = reopen_candidate_context(authority)
    supplied = require_hash(
        context.get("authorityHash"), "alternate-take context authority")
    core = {key: value for key, value in context.items()
            if key != "authorityHash"}
    if digest(core) != supplied \
            or supplied != authority.package.get("contextAuthorityHash"):
        raise AlternateTakeAuthorityError(
            "alternate-take context is stale or substituted")
    return context


def _selection_path(authority: CandidateAuthority) -> str:
    descriptor = authority.package.get("reviewCandidateDescriptorPath")
    if not isinstance(descriptor, str):
        raise AlternateTakeAuthorityError(
            "candidate descriptor path is absent")
    path = os.path.join(os.path.dirname(descriptor), _RECEIPT_NAME)
    if os.path.abspath(path) != path or os.path.realpath(
            os.path.dirname(path)) != os.path.dirname(path):
        raise AlternateTakeAuthorityError(
            "alternate-take receipt path is not canonical")
    return path


def _expected_source_frames(operation: dict) -> dict:
    frame_range = operation.get("sourceVideoFrameRange")
    if not isinstance(frame_range, dict) or set(frame_range) != {
            "startFrame", "endFrameExclusive"}:
        raise AlternateTakeAuthorityError(
            "source video frame authority is absent")
    rate = PositiveRational.from_value(operation.get("sourceFrameRate"))
    return {
        "firstFrame": frame_range["startFrame"],
        "endFrameExclusive": frame_range["endFrameExclusive"],
        "fpsNumerator": rate.numerator,
        "fpsDenominator": rate.denominator,
    }


def _bind_selected(
    authority: CandidateAuthority,
    candidate: dict,
    context: dict,
) -> None:
    extension = authority.operation.get("sourceExtension")
    expected_samples = {
        **(extension if isinstance(extension, dict) else {}),
        "sampleRate": authority.operation.get("sourceSampleRate"),
    }
    pairs = (
        (candidate.get("sourceId"), authority.source_id),
        (candidate.get("sourceMediaPath"), authority.source_media_path),
        (candidate.get("sourceMediaSha256"), authority.source_media_sha256),
        (candidate.get("sourceSampleRange"), expected_samples),
        (candidate.get("sourceFrameRange"),
         _expected_source_frames(authority.operation)),
        (candidate.get("outputFrameRange"),
         alternate_take_output_range(context, authority.operation)),
    )
    if any(observed != expected for observed, expected in pairs):
        raise AlternateTakeAuthorityError(
            "selected take is not the exact rendered operation range")


def _selection_core(
    authority: CandidateAuthority,
    candidate_set: dict,
    candidate: dict,
    region: dict,
) -> dict:
    policy = released_selection_policy()
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-alternate-take-selection-binding",
        "preparationHash": authority.preparation_hash,
        "operationHash": authority.descriptor["operationHash"],
        "candidateSetHash": candidate_set["candidateSetHash"],
        "selectionPolicyHash": digest(policy),
        "selectedCandidateId": candidate["candidateId"],
        "selectedCandidateHash": candidate["candidateHash"],
        "sourceId": candidate["sourceId"],
        "sourceMediaPath": candidate["sourceMediaPath"],
        "sourceMediaSha256": candidate["sourceMediaSha256"],
        "sourceSampleRange": candidate["sourceSampleRange"],
        "sourceFrameRange": candidate["sourceFrameRange"],
        "outputFrameRange": candidate["outputFrameRange"],
        "visualSpeechRegion": region,
    }


def _receipt(
    authority: CandidateAuthority,
    context: dict,
    candidate_set: dict,
    decision: AlternateTakeDecision,
) -> dict:
    rebuilt = validate_alternate_take_candidate_set(
        candidate_set, context, authority.operation)
    candidate, region = select_candidate(rebuilt, decision)
    _bind_selected(authority, candidate, context)
    selection_core = _selection_core(
        authority, rebuilt, candidate, region)
    core = {
        "schemaVersion": 1,
        "kind": "cut-repair-alternate-take-selection",
        "status": "selected-pending-visual-qc",
        "preparationHash": authority.preparation_hash,
        "operationHash": authority.descriptor["operationHash"],
        "contextAuthorityHash": rebuilt["contextAuthorityHash"],
        "sourceSnapshotSetHash": rebuilt["sourceSnapshotSetHash"],
        "transcriptTimingHash": rebuilt["transcriptTimingHash"],
        "retakeReportHash": rebuilt["retakeReportHash"],
        "candidateSet": rebuilt,
        "candidateSetHash": rebuilt["candidateSetHash"],
        "selectionPolicy": released_selection_policy(),
        "selectionPolicyHash": selection_core["selectionPolicyHash"],
        "selectedCandidateId": candidate["candidateId"],
        "selectedCandidateHash": candidate["candidateHash"],
        "sourceId": candidate["sourceId"],
        "sourceMediaPath": candidate["sourceMediaPath"],
        "sourceMediaSha256": candidate["sourceMediaSha256"],
        "sourceSampleRange": candidate["sourceSampleRange"],
        "sourceFrameRange": candidate["sourceFrameRange"],
        "outputFrameRange": candidate["outputFrameRange"],
        "visualSpeechRegion": region,
        "pictureChanged": True,
        "selectionHash": digest(selection_core),
    }
    return {**core, "receiptHash": digest(core)}


def _validate_receipt(
    authority: CandidateAuthority,
    context: dict,
    receipt: dict,
) -> dict:
    validate_document(_SCHEMA, receipt)
    decision = AlternateTakeDecision(
        receipt["selectedCandidateId"], receipt["selectionPolicy"],
        receipt["visualSpeechRegion"])
    expected = _receipt(
        authority, context, receipt["candidateSet"], decision)
    if receipt != expected:
        raise AlternateTakeAuthorityError(
            "alternate-take selection receipt is stale or tampered")
    return receipt


def publish_alternate_take_selection(
    producer: str,
    preparation_hash: str,
    candidate_set: dict,
    decision: AlternateTakeDecision,
) -> tuple[dict, str, str]:
    """Publish one create-once selection beside the rendered descriptor."""
    try:
        from edit.cut_repair_candidate_qc_contract import (
            load_candidate_authority_base,
        )
        authority = load_candidate_authority_base(
            producer, preparation_hash)
        if not authority.picture_dirty:
            raise AlternateTakeAuthorityError(
                "audio-only repair cannot publish alternate-take authority")
        receipt = _receipt(authority, _context(authority), candidate_set, decision)
        validate_document(_SCHEMA, receipt)
        path = _selection_path(authority)
        publish_json(path, receipt)
        return receipt, receipt["receiptHash"], path
    except AlternateTakeAuthorityError:
        raise
    except (
            ContextMaterializationError, SchemaValidationError,
            TimingContractError, KeyError, TypeError, ValueError, OSError,
    ) as exc:
        raise AlternateTakeAuthorityError(
            "alternate-take selection publication failed closed") from exc


def _private_receipt(path: str) -> None:
    row = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1 \
            or os.path.islink(path) or os.path.realpath(path) != path:
        raise AlternateTakeAuthorityError(
            "alternate-take receipt is not a private regular file")


def load_alternate_take_selection(
    authority: CandidateAuthority,
) -> tuple[dict, str, str]:
    """Reopen and semantically rederive the mandatory picture selection."""
    try:
        path = _selection_path(authority)
        _private_receipt(path)
        receipt, _ = stable_json(path, "alternate-take selection receipt")
        validated = _validate_receipt(authority, _context(authority), receipt)
        return validated, validated["receiptHash"], path
    except AlternateTakeAuthorityError:
        raise
    except (
            ContextMaterializationError, SchemaValidationError,
            TimingContractError, KeyError, TypeError, ValueError, OSError,
    ) as exc:
        raise AlternateTakeAuthorityError(
            "alternate-take selection is missing, stale, or unreadable") from exc

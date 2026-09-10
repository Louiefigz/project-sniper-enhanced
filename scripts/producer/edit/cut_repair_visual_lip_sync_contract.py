"""Closed promotion contract for embedded visual lip-sync evidence."""
from __future__ import annotations

from edit.cut_repair_candidate_qc_types import CandidateQcContractError
from edit.cut_repair_context_sources import (
    digest,
    require_hash,
    require_keys,
)
from edit.cut_repair_visual_lip_sync_types import (
    VISUAL_IMPLEMENTATION_NONCLAIMS,
    VISUAL_IMPLEMENTATION_ROLES,
    VISUAL_IMPLEMENTATION_SCOPE,
)

VISUAL_SEAM_FIELDS = {
    "alternateTakeSelectionReceiptHash",
    "visualOracleReceiptHash",
    "visualOracleReceipt",
    "sourceFrameRange",
    "sourceSampleRange",
    "outputFrameRange",
    "outputSampleRange",
}
_COMMON = {
    "schemaVersion", "kind", "status", "protocol", "evidenceSemantics",
    "preparationHash", "operationHash", "candidateCompositeSha256",
    "alternateTakeSelectionReceiptHash", "candidateSetHash", "selectionHash",
    "selectedCandidateId", "sourceId", "sourceMediaSha256",
    "sourceFrameRange", "sourceSampleRange", "outputFrameRange",
    "outputSampleRange", "visualSpeechRegionPpm",
}
_HASH_FIELDS = {
    "toolManifestHash", "ffmpegSha256", "runtimeSha256",
    "implementationSha256", "implementationClosureHash",
    "policySha256", "policyHash",
    "sourceVisualTraceSha256", "candidateVisualTraceSha256",
    "sourcePcmSha256", "candidatePcmSha256",
}
_TOOLS_TRACES = _HASH_FIELDS | {"implementationFileHashes"}
_TOOLS_TRACES |= {"implementationScope", "implementationNonClaims"}
_MEASUREMENTS = {
    "visibleUncoveredFrameCount", "visualDynamicPpm", "visualScorePpm",
    "visualPeakSeparationPpm", "audioScorePpm",
    "audioPeakSeparationPpm", "visualMappingOffsetFrames",
    "audioMappingOffsetFrames", "avOffsetFrames",
    "maximumMappingOffsetFrames", "maximumAvOffsetFrames",
    "lipSyncDisposition",
}
_VISUAL_KEYS = _COMMON | _TOOLS_TRACES | _MEASUREMENTS
_FRAME_KEYS = {
    "firstFrame", "endFrameExclusive", "fpsNumerator", "fpsDenominator"}
_SAMPLE_KEYS = {
    "startSample", "endSampleExclusive", "sampleRate"}
_REGION_KEYS = {"x", "y", "width", "height"}
def _integer(value: object, minimum: int, label: str) -> int:
    if type(value) is not int or value < minimum:
        raise CandidateQcContractError(f"{label} is malformed")
    return value


def _frame_range(value: object, label: str) -> None:
    if not isinstance(value, dict):
        raise CandidateQcContractError(f"{label} is absent")
    require_keys(value, _FRAME_KEYS, _FRAME_KEYS, label)
    first = _integer(value.get("firstFrame"), 0, label)
    end = _integer(value.get("endFrameExclusive"), 1, label)
    numerator = _integer(value.get("fpsNumerator"), 1, label)
    denominator = _integer(value.get("fpsDenominator"), 1, label)
    if end <= first or numerator <= 0 or denominator <= 0:
        raise CandidateQcContractError(f"{label} is empty")


def _sample_range(value: object, label: str) -> None:
    if not isinstance(value, dict):
        raise CandidateQcContractError(f"{label} is absent")
    require_keys(value, _SAMPLE_KEYS, _SAMPLE_KEYS, label)
    start = _integer(value.get("startSample"), 0, label)
    end = _integer(value.get("endSampleExclusive"), 1, label)
    rate = _integer(value.get("sampleRate"), 1, label)
    if end <= start or rate <= 0:
        raise CandidateQcContractError(f"{label} is empty")


def _region(value: object) -> None:
    if not isinstance(value, dict):
        raise CandidateQcContractError("visual speech region is absent")
    require_keys(value, _REGION_KEYS, _REGION_KEYS, "visual speech region")
    x = _integer(value.get("x"), 0, "visual speech region")
    y = _integer(value.get("y"), 0, "visual speech region")
    width = _integer(value.get("width"), 1, "visual speech region")
    height = _integer(value.get("height"), 1, "visual speech region")
    if x + width > 1_000_000 or y + height > 1_000_000:
        raise CandidateQcContractError("visual speech region escapes frame")


def _hashes(receipt: dict) -> None:
    for name in _HASH_FIELDS | {
            "preparationHash", "operationHash", "candidateCompositeSha256",
            "alternateTakeSelectionReceiptHash", "candidateSetHash",
            "selectionHash", "sourceMediaSha256"}:
        require_hash(receipt.get(name), f"visual receipt {name}")


def _implementation_files(value: object) -> None:
    if not isinstance(value, list) or len(value) != len(
            VISUAL_IMPLEMENTATION_ROLES):
        raise CandidateQcContractError(
            "visual implementation file hashes are absent")
    for item, role in zip(value, VISUAL_IMPLEMENTATION_ROLES):
        keys = {"role", "sha256"}
        if not isinstance(item, dict):
            raise CandidateQcContractError(
                "visual implementation file hash is malformed")
        require_keys(item, keys, keys, "visual implementation file hash")
        if item.get("role") != role:
            raise CandidateQcContractError(
                "visual implementation file role is stale")
        require_hash(item.get("sha256"), f"visual {role} implementation")


def _measurements(receipt: dict) -> None:
    positive = (
        "visibleUncoveredFrameCount", "visualDynamicPpm",
        "visualPeakSeparationPpm", "audioPeakSeparationPpm")
    scores = ("visualScorePpm", "audioScorePpm")
    offsets = (
        "visualMappingOffsetFrames", "audioMappingOffsetFrames",
        "avOffsetFrames")
    if any(_integer(receipt.get(name), 1, name) <= 0 for name in positive) \
            or any(not 0 <= _integer(receipt.get(name), 0, name) <= 1_000_000
                   for name in scores) \
            or any(type(receipt.get(name)) is not int for name in offsets):
        raise CandidateQcContractError("visual measurements are malformed")
    mapping = _integer(
        receipt.get("maximumMappingOffsetFrames"), 1, "mapping tolerance")
    av = _integer(
        receipt.get("maximumAvOffsetFrames"), 1, "A/V tolerance")
    released = (
        receipt["visibleUncoveredFrameCount"] >= 12
        and receipt["visualDynamicPpm"] >= 6_000
        and receipt["visualScorePpm"] >= 940_000
        and receipt["audioScorePpm"] >= 940_000
        and receipt["visualPeakSeparationPpm"] >= 2_500
        and receipt["audioPeakSeparationPpm"] >= 2_500
        and mapping == 1 and av == 1)
    if not released \
            or abs(receipt["visualMappingOffsetFrames"]) > mapping \
            or abs(receipt["audioMappingOffsetFrames"]) > mapping \
            or abs(receipt["avOffsetFrames"]) > av:
        raise CandidateQcContractError(
            "visual lip-sync released thresholds were not proved")


def validate_visual_receipt(
    receipt: object,
    operation_hash: str,
    candidate_hash: str,
    selection_receipt_hash: str,
) -> dict:
    """Validate exact visual evidence and all promotion-relevant bindings."""
    if not isinstance(receipt, dict):
        raise CandidateQcContractError("visual oracle receipt is absent")
    require_keys(
        receipt, _VISUAL_KEYS, _VISUAL_KEYS, "visual lip-sync receipt")
    expected = (
        1, "cut-repair-visual-lip-sync-qc", "bounded-pass",
        "deterministic-selected-source-av-offset-v1",
        "caller-supplied-roi-source-av-temporal-mapping-"
        "not-face-mouth-or-phoneme-proof",
        operation_hash, candidate_hash, selection_receipt_hash, "passed")
    observed = (
        receipt.get("schemaVersion"), receipt.get("kind"),
        receipt.get("status"), receipt.get("protocol"),
        receipt.get("evidenceSemantics"), receipt.get("operationHash"),
        receipt.get("candidateCompositeSha256"),
        receipt.get("alternateTakeSelectionReceiptHash"),
        receipt.get("lipSyncDisposition"))
    if observed != expected:
        raise CandidateQcContractError("visual lip-sync receipt is stale")
    _hashes(receipt)
    if receipt.get("implementationScope") != VISUAL_IMPLEMENTATION_SCOPE \
            or receipt.get("implementationNonClaims") \
            != list(VISUAL_IMPLEMENTATION_NONCLAIMS):
        raise CandidateQcContractError(
            "visual implementation scope or nonclaims are stale")
    _implementation_files(receipt.get("implementationFileHashes"))
    _frame_range(receipt.get("sourceFrameRange"), "source frame range")
    _frame_range(receipt.get("outputFrameRange"), "output frame range")
    _sample_range(receipt.get("sourceSampleRange"), "source sample range")
    _sample_range(receipt.get("outputSampleRange"), "output sample range")
    _region(receipt.get("visualSpeechRegionPpm"))
    _measurements(receipt)
    return receipt


def visual_seam_closure(receipt: dict) -> dict:
    """Embed exact source/output ranges and the complete visual proof."""
    selection_hash = require_hash(
        receipt.get("alternateTakeSelectionReceiptHash"),
        "alternate-take selection receipt")
    validate_visual_receipt(
        receipt, receipt.get("operationHash"),
        receipt.get("candidateCompositeSha256"), selection_hash)
    return {
        "alternateTakeSelectionReceiptHash": selection_hash,
        "visualOracleReceiptHash": digest(receipt),
        "visualOracleReceipt": receipt,
        "sourceFrameRange": receipt["sourceFrameRange"],
        "sourceSampleRange": receipt["sourceSampleRange"],
        "outputFrameRange": receipt["outputFrameRange"],
        "outputSampleRange": receipt["outputSampleRange"],
    }


def validate_visual_seam(
    seam: dict,
    operation_hash: str,
    candidate_hash: str,
) -> None:
    """Reject a visual pass whose nested proof or copied ranges are stale."""
    selection_hash = require_hash(
        seam.get("alternateTakeSelectionReceiptHash"),
        "seam alternate-take selection")
    visual_hash = require_hash(
        seam.get("visualOracleReceiptHash"), "seam visual receipt")
    receipt = validate_visual_receipt(
        seam.get("visualOracleReceipt"), operation_hash,
        candidate_hash, selection_hash)
    if digest(receipt) != visual_hash:
        raise CandidateQcContractError("embedded visual receipt hash is stale")
    for name in (
            "sourceFrameRange", "sourceSampleRange",
            "outputFrameRange", "outputSampleRange"):
        if seam.get(name) != receipt.get(name):
            raise CandidateQcContractError(
                f"seam {name} does not close over visual evidence")

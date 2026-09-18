#!/usr/bin/env python3
"""Assemble promotion evidence only from controller-owned QC receipts."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

from edit.cut_repair_context_sources import (
    digest, require_hash, require_keys, stable_json,
)
from edit.cut_repair_candidate_qc_types import CandidateQcContractError
from edit import cut_repair_visual_lip_sync_contract as visual_contract
from edit.cut_repair_promotion_candidate import (
    PromotionCandidate,
    PromotionGateError,
    inside_staging,
    load_promotion_candidate,
)
_COMMON = {"schemaVersion", "kind", "status", "operationHash",
           "candidateCompositeSha256"}
_SPECS = {
    "alignment": (
        "bounded-pass", "cut-repair-alignment-qc", {
            "alignmentProtocol", "evidenceSemantics", "runtimeSha256",
            "implementationSha256", "policySha256", "sourceMediaSha256",
            "candidateWaveSha256", "referenceWaveSha256", "targetWordIds",
            "observedOccurrenceCount", "sourceSpanBoundaryMatch",
            "bestScorePpm", "minimumScorePpm",
            "matchStartSampleInCandidateWindow", "boundaryToleranceSamples",
            "referenceSampleCount",
        }),
    "vad": (
        "bounded-pass", "cut-repair-vad-qc", {
            "runtimeSha256", "speechContinuityPassed",
            "unintendedSpeechGapCount",
        }),
    "retranscription": (
        "bounded-pass", "cut-repair-retranscription-qc", {
            "runtimeSha256", "modelSha256", "targetPhraseHash",
            "observedOccurrenceCount", "wordOrderPreserved",
        }),
    "seam": (
        "bounded-pass", "cut-repair-seam-qc", {
            "runtimeSha256", "clickFree", "duplicateFree",
            "roomToneContinuous", "lipSyncDisposition",
        }),
    "audition": (
        "operator-approved-candidate", "cut-repair-audition-qc", {
            "operatorReceiptId", "approvalPolicyHash", "reviewedAt",
            "decision", "reportedDamageResolved",
        }),
}


def _hash_fields(receipt: dict, names: tuple[str, ...], lane: str) -> None:
    for name in names:
        require_hash(receipt.get(name), f"{lane} receipt {name}")


def _assert_alignment(receipt: dict) -> None:
    _hash_fields(receipt, (
        "runtimeSha256", "implementationSha256", "policySha256",
        "sourceMediaSha256", "candidateWaveSha256",
        "referenceWaveSha256"), "alignment")
    words = receipt.get("targetWordIds")
    integers = (
        receipt.get("bestScorePpm"), receipt.get("minimumScorePpm"),
        receipt.get("matchStartSampleInCandidateWindow"),
        receipt.get("boundaryToleranceSamples"),
        receipt.get("referenceSampleCount"),
    )
    if receipt.get("alignmentProtocol") != \
            "deterministic-source-waveform-v1" \
            or receipt.get("evidenceSemantics") != \
            "transcript-bound-source-waveform-presence-not-audibility" \
            or not isinstance(words, list) or not words \
            or any(not isinstance(word, str) or not word for word in words) \
            or len(set(words)) != len(words) \
            or any(type(value) is not int or value < 0 for value in integers) \
            or receipt.get("minimumScorePpm") != 850_000 \
            or receipt.get("bestScorePpm") < 850_000 \
            or receipt.get("bestScorePpm") > 1_000_000 \
            or receipt.get("boundaryToleranceSamples") != 240 \
            or receipt.get("referenceSampleCount") <= 0 \
            or receipt.get("observedOccurrenceCount") != 1 \
            or receipt.get("sourceSpanBoundaryMatch") is not True:
        raise PromotionGateError(
            "alignment did not prove one transcript-bound source waveform")


def _assert_lane_fields(
    lane: str,
    receipt: dict,
    candidate: PromotionCandidate,
) -> None:
    if lane == "alignment":
        _assert_alignment(receipt)
        return
    if lane == "vad":
        _hash_fields(receipt, ("runtimeSha256",), lane)
        if receipt.get("speechContinuityPassed") is not True \
                or receipt.get("unintendedSpeechGapCount") != 0:
            raise PromotionGateError("VAD did not prove continuous speech")
        return
    if lane == "retranscription":
        _hash_fields(
            receipt,
            ("runtimeSha256", "modelSha256", "targetPhraseHash"), lane)
        if receipt.get("observedOccurrenceCount") != 1 \
                or receipt.get("wordOrderPreserved") is not True:
            raise PromotionGateError(
                "retranscription did not prove the target phrase")
        return
    if lane == "seam":
        _hash_fields(receipt, ("runtimeSha256",), lane)
        required = ("passed" if candidate.picture_dirty
                    else "not-applicable-audio-only")
        if receipt.get("clickFree") is not True \
                or receipt.get("duplicateFree") is not True \
                or receipt.get("roomToneContinuous") is not True \
                or receipt.get("lipSyncDisposition") != required:
            raise PromotionGateError("seam QC did not pass")
        if candidate.picture_dirty:
            _assert_visual_binding(receipt, candidate)
        return
    _audition(receipt)


def _assert_visual_binding(
    receipt: dict,
    candidate: PromotionCandidate,
) -> None:
    try:
        visual_contract.validate_visual_seam(
            receipt, receipt["operationHash"],
            receipt["candidateCompositeSha256"])
    except CandidateQcContractError as exc:
        raise PromotionGateError(
            "seam visual lip-sync proof is stale") from exc
    if receipt.get("alternateTakeSelectionReceiptHash") \
            != candidate.selection_receipt_hash:
        raise PromotionGateError(
            "seam visual proof binds another take selection")
    visual = receipt.get("visualOracleReceipt")
    expected = candidate.visual_binding
    if not isinstance(visual, dict) or not isinstance(expected, dict) \
            or any(visual.get(name) != value
                   for name, value in expected.items()):
        raise PromotionGateError(
            "seam visual proof contradicts alternate-take authority")


def _audition(receipt: dict) -> None:
    require_hash(receipt.get("approvalPolicyHash"), "audition approval policy")
    reviewed = receipt.get("reviewedAt")
    try:
        parsed = datetime.fromisoformat(
            reviewed.replace("Z", "+00:00")) if isinstance(
                reviewed, str) else None
    except ValueError as exc:
        raise PromotionGateError("audition timestamp is invalid") from exc
    if not receipt.get("operatorReceiptId") or parsed is None \
            or receipt.get("decision") != "approved" \
            or receipt.get("reportedDamageResolved") is not True:
        raise PromotionGateError(
            "audition lacks explicit candidate approval")


def _receipt(
    qc_dir: str,
    lane: str,
    candidate: PromotionCandidate,
) -> dict:
    status, kind, fields = _SPECS[lane]
    path = os.path.join(qc_dir, f"{lane}.json")
    receipt, _ = stable_json(path, f"{lane} QC receipt")
    if lane == "seam" and receipt.get("lipSyncDisposition") == "passed":
        fields = fields | visual_contract.VISUAL_SEAM_FIELDS
    require_keys(receipt, _COMMON | fields, _COMMON | fields, f"{lane} receipt")
    observed = (
        receipt.get("schemaVersion"), receipt.get("kind"),
        receipt.get("status"), receipt.get("operationHash"),
        receipt.get("candidateCompositeSha256"),
    )
    expected = (
        1, kind, status, candidate.operation_hash,
        candidate.composite_sha256,
    )
    if observed != expected:
        raise PromotionGateError(f"{lane} receipt is stale or substituted")
    _assert_lane_fields(lane, receipt, candidate)
    return {
        "status": status, "receiptHash": digest(receipt),
        "candidateCompositeSha256": candidate.composite_sha256,
        "receipt": receipt,
    }


def build_promotion_evidence(producer: str, candidate_path: str,
                             qc_dir: str,
                             preparation_hash: str | None = None) -> dict:
    """Reopen all receipts and emit the cross-runtime promotion envelope."""
    producer = os.path.realpath(producer)
    candidate = load_promotion_candidate(
        producer, candidate_path, preparation_hash)
    qc_dir = inside_staging(
        qc_dir, candidate.staging_root, "QC directory")
    if not os.path.isdir(qc_dir):
        raise PromotionGateError("QC authority is not a directory")
    lanes = {lane: _receipt(qc_dir, lane, candidate) for lane in _SPECS}
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-promotion-evidence",
        "operationHash": candidate.operation_hash,
        "candidateCompositeSha256": candidate.composite_sha256,
        **lanes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("producer_dir")
    parser.add_argument("candidate_path")
    parser.add_argument("qc_dir")
    parser.add_argument("preparation_hash", nargs="?")
    args = parser.parse_args()
    try:
        print(json.dumps(build_promotion_evidence(
            os.path.abspath(args.producer_dir),
            os.path.abspath(args.candidate_path),
            os.path.abspath(args.qc_dir),
            args.preparation_hash),
            ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Post-render P2 promotion requires actual bound QC receipt objects."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import types
import unittest

from edit.cut_repair_promotion_gate import (
    PromotionGateError,
    build_promotion_evidence,
)
from tests._p2_candidate_qc_fixture import CandidateQcFixture

HASH = "a" * 64


def _write(path: str, value: object) -> None:
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)


def _common(fixture: "_Fixture", kind: str, status: str) -> dict:
    return {
        "schemaVersion": 1, "kind": kind, "status": status,
        "operationHash": fixture.operation_hash,
        "candidateCompositeSha256": fixture.composite_hash,
    }


def _alignment_receipt(fixture: "_Fixture") -> dict:
    return {
        **_common(fixture, "cut-repair-alignment-qc", "bounded-pass"),
        "alignmentProtocol": "deterministic-source-waveform-v1",
        "evidenceSemantics":
            "transcript-bound-source-waveform-presence-not-audibility",
        "runtimeSha256": "1" * 64,
        "implementationSha256": "2" * 64,
        "policySha256": "3" * 64,
        "sourceMediaSha256": "4" * 64,
        "candidateWaveSha256": "5" * 64,
        "referenceWaveSha256": "6" * 64,
        "targetWordIds": ["word-1"],
        "observedOccurrenceCount": 1,
        "sourceSpanBoundaryMatch": True,
        "bestScorePpm": 990_000,
        "minimumScorePpm": 850_000,
        "matchStartSampleInCandidateWindow": 48_000,
        "boundaryToleranceSamples": 240,
        "referenceSampleCount": 24_000,
    }


def _receipts(fixture: "_Fixture") -> dict[str, dict]:
    return {
        "alignment": _alignment_receipt(fixture),
        "vad": {
            **_common(fixture, "cut-repair-vad-qc", "bounded-pass"),
            "runtimeSha256": "4" * 64,
            "speechContinuityPassed": True,
            "unintendedSpeechGapCount": 0,
        },
        "retranscription": {
            **_common(
                fixture, "cut-repair-retranscription-qc", "bounded-pass"),
            "runtimeSha256": "5" * 64, "modelSha256": "6" * 64,
            "targetPhraseHash": "7" * 64,
            "observedOccurrenceCount": 1, "wordOrderPreserved": True,
        },
        "seam": {
            **_common(fixture, "cut-repair-seam-qc", "bounded-pass"),
            "runtimeSha256": "8" * 64, "clickFree": True,
            "duplicateFree": True, "roomToneContinuous": True,
            "lipSyncDisposition": "not-applicable-audio-only",
        },
        "audition": {
            **_common(
                fixture, "cut-repair-audition-qc",
                "operator-approved-candidate"),
            "operatorReceiptId": "operator-1",
            "approvalPolicyHash": "9" * 64,
            "reviewedAt": "2026-07-29T12:00:00.000Z",
            "decision": "approved", "reportedDamageResolved": True,
        },
    }


class _Fixture:
    def __init__(self) -> None:
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.producer = os.path.join(self.root, "producer")
        self.attempt = os.path.join(
            self.producer, ".sniper-cut-repair-staging", "attempt-1")
        self.qc = os.path.join(self.attempt, "qc")
        os.makedirs(self.qc)
        self.operation_hash = HASH
        self.composite_path = os.path.join(self.attempt, "candidate.mov")
        with open(self.composite_path, "wb") as stream:
            stream.write(b"candidate media")
        self.composite_hash = hashlib.sha256(b"candidate media").hexdigest()
        self.candidate_path = os.path.join(self.attempt, "candidate.json")
        _write(self.candidate_path, {
            "schemaVersion": 1, "kind": "cut-repair-candidate",
            "status": "candidate-proved",
            "operationHash": self.operation_hash,
            "fragmentReceipt": {
                "operationHash": self.operation_hash,
                "method": "audio-lj-overlap",
            },
            "compositeReceipt": {
                "operationHash": self.operation_hash,
                "output": {
                    "path": self.composite_path,
                    "sha256": self.composite_hash,
                },
            },
        })
        self.receipts = _receipts(self)
        self.write_receipts()

    def rendered_candidate(self) -> str:
        candidate_path = os.path.join(
            self.attempt, "rendered-plan-candidate.json")
        _write(candidate_path, {
            "schemaVersion": 1,
            "kind": "cut-repair-rendered-plan-candidate",
            "status": "candidate-proved",
            "operationHash": self.operation_hash,
            "reviewPlanObjectHash": "1" * 64,
            "reviewPlanContentHash": "2" * 64,
            "reviewTimelineMapHash": "3" * 64,
            "reviewRenderGraphHash": "4" * 64,
            "reviewRenderGraphReceiptHash": "5" * 64,
            "reviewRenderGraphCandidatePointerHash": "6" * 64,
            "candidatePath": self.composite_path,
            "candidateSha256": self.composite_hash,
        })
        return candidate_path

    def write_receipts(self) -> None:
        for lane, receipt in self.receipts.items():
            _write(os.path.join(self.qc, f"{lane}.json"), receipt)

    def clean(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class CutRepairPromotionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _Fixture()

    def tearDown(self) -> None:
        self.fixture.clean()

    def test_full_receipt_set_builds_embedded_evidence(self) -> None:
        evidence = build_promotion_evidence(
            self.fixture.producer,
            self.fixture.candidate_path,
            self.fixture.qc)
        alignment = evidence["alignment"]
        self.assertEqual(
            alignment["receipt"], self.fixture.receipts["alignment"])
        self.assertEqual(len(alignment["receiptHash"]), 64)
        self.assertEqual(
            evidence["candidateCompositeSha256"],
            self.fixture.composite_hash)

    def test_rendered_plan_candidate_drives_same_qc_envelope(self) -> None:
        fixture = CandidateQcFixture()
        try:
            descriptor_path = os.path.join(
                fixture.staging, "cut-repair-rendered-candidate.json")
            with open(descriptor_path, encoding="utf-8") as stream:
                descriptor = json.load(stream)
            receipt_fixture = types.SimpleNamespace(
                operation_hash=descriptor["operationHash"],
                composite_hash=fixture.candidate_hash)
            receipts = _receipts(receipt_fixture)
            qc = os.path.join(fixture.staging, "promotion-qc")
            os.makedirs(qc)
            for lane, receipt in receipts.items():
                _write(os.path.join(qc, f"{lane}.json"), receipt)
            evidence = build_promotion_evidence(
                fixture.producer, descriptor_path, qc,
                fixture.preparation_hash)
            self.assertEqual(
                evidence["candidateCompositeSha256"],
                fixture.candidate_hash)
        finally:
            fixture.clean()

    def test_rendered_plan_candidate_requires_preparation_authority(self) -> None:
        candidate_path = self.fixture.rendered_candidate()
        with self.assertRaisesRegex(
                PromotionGateError, "preparation authority"):
            build_promotion_evidence(
                self.fixture.producer, candidate_path, self.fixture.qc)

    def test_audio_candidate_cannot_claim_picture_visual_pass(self) -> None:
        self.fixture.receipts["seam"]["lipSyncDisposition"] = "passed"
        self.fixture.write_receipts()
        with self.assertRaisesRegex(ValueError, "unknown or missing|seam"):
            build_promotion_evidence(
                self.fixture.producer,
                self.fixture.candidate_path,
                self.fixture.qc)

    def test_missing_operator_audition_fails_closed(self) -> None:
        os.unlink(os.path.join(self.fixture.qc, "audition.json"))
        with self.assertRaises(FileNotFoundError):
            build_promotion_evidence(
                self.fixture.producer,
                self.fixture.candidate_path,
                self.fixture.qc)

    def test_semantically_false_vad_receipt_fails_closed(self) -> None:
        self.fixture.receipts["vad"]["speechContinuityPassed"] = False
        self.fixture.write_receipts()
        with self.assertRaisesRegex(
                PromotionGateError, "continuous speech"):
            build_promotion_evidence(
                self.fixture.producer,
                self.fixture.candidate_path,
                self.fixture.qc)

    def test_changed_composite_bytes_fail_closed(self) -> None:
        with open(self.fixture.composite_path, "ab") as stream:
            stream.write(b"-changed")
        with self.assertRaisesRegex(
                PromotionGateError, "bytes are stale"):
            build_promotion_evidence(
                self.fixture.producer,
                self.fixture.candidate_path,
                self.fixture.qc)


if __name__ == "__main__":
    unittest.main(verbosity=2)

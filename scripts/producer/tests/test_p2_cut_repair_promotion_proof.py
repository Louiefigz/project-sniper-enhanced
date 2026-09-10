"""Promotion-proof minting from controller-bound P2 preparation authority."""
from __future__ import annotations

import copy
import unittest

from contracts.schema_validator import validate_document
from edit.cut_repair_promotion_proof import build_promotion_proof
from edit.exact_timing import PositiveRational, ProjectClock
from edit.picture_lock_common import content_hash
from _p2_repair_media_fixture import operation


def _revision() -> dict:
    return {
        "schemaVersion": 2,
        "parentRevisionHash": "1" * 64,
        "planContentHash": "2" * 64,
        "manifestHash": "3" * 64,
        "sourceSnapshotSetHash": "4" * 64,
        "transcriptTimingHash": "a" * 64,
        "timelineMapHash": "5" * 64,
        "canvasProfileHash": "6" * 64,
        "destinationProfileHashes": [],
        "pictureLockHash": None,
        "workflowState": "CUT_REVIEW",
        "requestLedgerHash": "7" * 64,
        "renderGraphHash": "8" * 64,
        "projectionReceiptHash": None,
        "authoritativeSidecars": {},
        "planObjectHash": "9" * 64,
    }


def _receipt(kind: str, operation_hash: str) -> dict:
    return {
        "schemaVersion": 1,
        "kind": kind,
        "operationHash": operation_hash,
        "exactOutputDurationPreserved": True,
        "output": {"path": "/private/staged.mov", "sha256": "b" * 64},
    }


def _fragment_receipt(action: dict, operation_hash: str) -> dict:
    return {
        **_receipt("cut-repair-fragment", operation_hash),
        "retime": {
            "requestedSpeed": action["speed"],
            "sourceSampleRange": action["sourceExtension"],
            "sourceSampleRate": action["sourceSampleRate"],
            "normalizedSourceSampleRange": action["sourceExtension"],
            "outputSamples": action["extensionOutputSamples"],
            "effectiveRatio": action["speed"],
        },
    }


def _input() -> dict:
    action = operation(ProjectClock(PositiveRational(30, 1), 48_000))
    operation_hash = content_hash(action)
    revision = _revision()
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-promotion-proof-input",
        "operation": action,
        "operationHash": operation_hash,
        "fragmentReceipt": _fragment_receipt(action, operation_hash),
        "compositeReceipt": _receipt(
            "cut-repair-composite", operation_hash),
        "reviewRevision": revision,
        "reviewRevisionHash": content_hash(revision),
        "reviewReceiptHash": "c" * 64,
        "promotionEvidenceHash": "d" * 64,
        "selectedApproval": {
            "approver": "operator",
            "approvalPolicyHash": "e" * 64,
            "approvalReceiptHash": "f" * 64,
        },
        "workflowPolicy": "cut-first",
        "contextSegments": [{
            "segmentId": "segment-a",
            "elementVersion": 1,
            "sourceId": "source-a",
            "sourceRate": 48_000,
            "sourceSamples": {
                "startSample": 0,
                "endSampleExclusive": 240_000,
            },
            "outputFrames": {
                "startFrame": 0,
                "endFrameExclusive": 150,
            },
            "speed": {"numerator": "1", "denominator": "1"},
        }],
        "childCutTrack": [{
            "sourceId": "source-a",
            "start": 0.0,
            "end": 5.0,
            "speed": 1.0,
        }],
        "projectFps": {"numerator": "30", "denominator": "1"},
        "palmierSelected": False,
        "captionDialogueAuthority": None,
    }


class CutRepairPromotionProofTests(unittest.TestCase):
    def test_mints_real_lock_lineage_and_closed_caption_disposition(self) -> None:
        value = build_promotion_proof(_input())
        self.assertEqual(value["status"], "candidate-proved")
        self.assertEqual(
            value["childPictureLock"]["approvedCutRevisionHash"],
            _input()["reviewRevisionHash"])
        self.assertEqual(
            value["childPictureLock"]["cutApprovalReceiptHash"], "d" * 64)
        self.assertEqual(
            value["captionRevalidation"]["status"], "not-present")
        self.assertEqual(
            value["palmierDisposition"]["nativeStatus"], "skipped")
        validate_document(
            "picture-lock-v1.schema.json", value["childPictureLock"])
        validate_document(
            "picture-lock-supersession-v1.schema.json",
            value["supersessionReceipt"])
        validate_document(
            "caption-repair-revalidation-v1.schema.json",
            value["captionRevalidation"])

    def test_selected_approval_changes_child_lock_identity(self) -> None:
        first = build_promotion_proof(_input())
        changed = _input()
        changed["selectedApproval"]["approvalReceiptHash"] = "0" * 64
        second = build_promotion_proof(changed)
        self.assertNotEqual(
            first["childPictureLockHash"], second["childPictureLockHash"])
        self.assertNotEqual(
            first["invariantProofHash"], second["invariantProofHash"])

    def test_revision_segment_and_unknown_field_tampering_fail_closed(self) -> None:
        stale = _input()
        stale["reviewRevision"]["timelineMapHash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "CUT_REVIEW revision"):
            build_promotion_proof(stale)
        gap = _input()
        gap["contextSegments"][0]["outputFrames"]["startFrame"] = 1
        with self.assertRaisesRegex(ValueError, "cover the timeline"):
            build_promotion_proof(gap)
        unknown = copy.deepcopy(_input())
        unknown["approved"] = True
        with self.assertRaisesRegex(ValueError, "not closed"):
            build_promotion_proof(unknown)


if __name__ == "__main__":
    unittest.main(verbosity=2)

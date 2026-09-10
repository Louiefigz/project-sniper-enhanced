"""Python-side parent/action binding for the two-step P2 promotion."""
from __future__ import annotations

import unittest

from edit.picture_lock import (
    PictureLockInput,
    SelectedApproval,
    mint_picture_lock,
)
from edit.picture_lock_common import content_hash

HASH = {value: value * 64 for value in "abcdef0123456789"}


class TwoStepPromotionBindingTests(unittest.TestCase):
    def test_child_lock_approves_review_without_rebasing_repair(self) -> None:
        operation = {
            "schemaVersion": 1,
            "operation": "cut.restoreSpeech",
            "parentPictureLockHash": HASH["1"],
            "parentTimelineMapHash": HASH["2"],
        }
        operation_hash = content_hash(operation)
        lock, lock_hash = mint_picture_lock(PictureLockInput(
            approved_cut_revision_hash=HASH["3"],
            plan_content_hash=HASH["4"],
            timeline_map_hash=HASH["5"],
            source_snapshot_set_hash=HASH["6"],
            transcript_timing_hash=HASH["7"],
            cut_approval_receipt_hash=HASH["8"],
            cut_review_approval_receipt_hash=HASH["9"],
            workflow_policy="cut-first",
            selected_approval=SelectedApproval(
                "operator", HASH["a"], HASH["b"]),
            parent_picture_lock_hash=operation["parentPictureLockHash"],
        ))
        self.assertEqual(lock["approvedCutRevisionHash"], HASH["3"])
        self.assertEqual(lock["parentPictureLockHash"], HASH["1"])
        self.assertEqual(operation["parentTimelineMapHash"], HASH["2"])
        self.assertEqual(content_hash(operation), operation_hash)
        self.assertNotEqual(lock_hash, operation_hash)

    def test_selected_approval_is_part_of_child_lock_identity(self) -> None:
        common = {
            "approved_cut_revision_hash": HASH["3"],
            "plan_content_hash": HASH["4"],
            "timeline_map_hash": HASH["5"],
            "source_snapshot_set_hash": HASH["6"],
            "transcript_timing_hash": HASH["7"],
            "cut_approval_receipt_hash": HASH["8"],
            "cut_review_approval_receipt_hash": HASH["9"],
            "workflow_policy": "cut-first",
            "parent_picture_lock_hash": HASH["1"],
        }
        _, first = mint_picture_lock(PictureLockInput(
            **common,
            selected_approval=SelectedApproval(
                "operator", HASH["a"], HASH["b"]),
        ))
        _, second = mint_picture_lock(PictureLockInput(
            **common,
            selected_approval=SelectedApproval(
                "operator", HASH["a"], HASH["c"]),
        ))
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)

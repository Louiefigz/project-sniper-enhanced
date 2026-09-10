"""First-class picture-lock migration, proof, and lineage tests."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from edit.exact_timing import FrameRange, SampleRange
from edit.picture_lock import (
    CompatibilityLockEvidence,
    MappingProofInput,
    MappingSpan,
    PictureLockError,
    PictureLockInput,
    SelectedApproval,
    SupersessionInput,
    mint_picture_lock,
    mint_supersession,
    prove_unchanged_mapping,
)

H = {char: char * 64 for char in "abcdef0123456789"}


def _lock_input() -> PictureLockInput:
    ancestor = CompatibilityLockEvidence(
        lock_hash=H["a"],
        approved_cut_revision_hash=H["f"],
        plan_content_hash=H["b"],
        timeline_map_hash=H["c"],
        source_snapshot_set_hash=H["d"],
        transcript_timing_hash=H["e"],
        cut_approval_receipt_hash=H["0"],
        cut_review_approval_receipt_hash=H["1"],
    )
    return PictureLockInput(
        approved_cut_revision_hash=H["f"],
        plan_content_hash=H["b"],
        timeline_map_hash=H["c"],
        source_snapshot_set_hash=H["d"],
        transcript_timing_hash=H["e"],
        cut_approval_receipt_hash=H["0"],
        cut_review_approval_receipt_hash=H["1"],
        workflow_policy="cut-first",
        selected_approval=SelectedApproval(
            "operator", H["2"], H["3"]),
        compatibility_ancestor=ancestor,
    )


class PictureLockTests(unittest.TestCase):
    def test_selected_policy_mints_deterministic_first_class_lock(self) -> None:
        first, first_hash = mint_picture_lock(_lock_input())
        second, second_hash = mint_picture_lock(_lock_input())
        self.assertEqual(first, second)
        self.assertEqual(first_hash, second_hash)
        self.assertEqual(first["requiredCleanReviews"], 2)
        self.assertEqual(first["compatibilityAncestorHash"], H["a"])
        self.assertEqual(first["selectedApproval"]["approver"], "operator")
        self.assertNotIn("adapterVersion", first)

    def test_compatibility_cut_drift_cannot_be_reinterpreted_as_approval(self) -> None:
        item = _lock_input()
        changed = PictureLockInput(
            **{**item.__dict__, "timeline_map_hash": H["4"]})
        with self.assertRaisesRegex(PictureLockError, "timeline map"):
            mint_picture_lock(changed)

    def test_compatibility_receipt_drift_requires_normal_reapproval(self) -> None:
        item = _lock_input()
        changed = PictureLockInput(
            **{**item.__dict__, "cut_approval_receipt_hash": H["4"]})
        with self.assertRaisesRegex(PictureLockError, "cut approval"):
            mint_picture_lock(changed)


class UnchangedMappingProofTests(unittest.TestCase):
    def _proof(self, changed_after_dirty: bool = False) -> MappingProofInput:
        parent = (
            MappingSpan(
                FrameRange(0, 100), "raw",
                SampleRange(0, 160_000)),
        )
        after_start = 96_001 if changed_after_dirty else 96_000
        child = (
            MappingSpan(
                FrameRange(0, 40), "raw",
                SampleRange(0, 64_000)),
            MappingSpan(
                FrameRange(40, 60), "alternate",
                SampleRange(10_000, 42_000)),
            MappingSpan(
                FrameRange(60, 100), "raw",
                SampleRange(after_start, 160_000)),
        )
        return MappingProofInput(
            parent_timeline_map_hash=H["5"],
            child_timeline_map_hash=H["6"],
            parent=parent,
            child=child,
            dirty_windows=(FrameRange(40, 60),),
            total_frames=100,
        )

    def test_only_authorized_dirty_mapping_may_change(self) -> None:
        proof, proof_hash = prove_unchanged_mapping(self._proof())
        self.assertRegex(proof_hash, r"^[0-9a-f]{64}$")
        self.assertEqual(
            proof["authorizedDirtyWindows"],
            [{"startFrame": 40, "endFrameExclusive": 60}])
        self.assertTrue(proof["unchangedRanges"])

    def test_one_sample_foreign_change_outside_dirty_window_fails(self) -> None:
        with self.assertRaisesRegex(PictureLockError, "frame 60"):
            prove_unchanged_mapping(self._proof(changed_after_dirty=True))


class SupersessionTests(unittest.TestCase):
    def test_child_lock_records_clause_migration_and_revalidation(self) -> None:
        proof_input = UnchangedMappingProofTests()._proof()
        _, proof_hash = prove_unchanged_mapping(proof_input)
        receipt, receipt_hash = mint_supersession(SupersessionInput(
            parent_picture_lock_hash=H["7"],
            child_picture_lock_hash=H["8"],
            repair_operation_hash=H["9"],
            parent_timeline_map_hash=H["5"],
            child_timeline_map_hash=H["6"],
            dirty_windows=(FrameRange(40, 60),),
            mapping_proof=proof_input,
            superseded_clause_ids=("clause-1", "clause-2"),
            successor_clause_ids=("clause-1-v2", "clause-2-v2"),
            revalidated_operation_ids=("op-1",),
        ))
        self.assertRegex(receipt_hash, r"^[0-9a-f]{64}$")
        self.assertEqual(
            receipt["revalidatedCommittedOperationIds"], ["op-1"])
        self.assertEqual(receipt["supersededClauseIds"],
                         ["clause-1", "clause-2"])
        self.assertEqual(receipt["unchangedMappingProofHash"], proof_hash)

    def test_missing_successor_clause_fails_closed(self) -> None:
        with self.assertRaisesRegex(PictureLockError, "one explicit successor"):
            mint_supersession(SupersessionInput(
                H["7"], H["8"], H["9"], H["5"], H["6"],
                (FrameRange(40, 60),),
                UnchangedMappingProofTests()._proof(),
                ("clause-1",), (), (),
            ))

    def test_supersession_cannot_claim_an_unrelated_mapping_proof(self) -> None:
        proof = UnchangedMappingProofTests()._proof()
        with self.assertRaisesRegex(PictureLockError, "timeline hashes"):
            mint_supersession(SupersessionInput(
                H["7"], H["8"], H["9"], H["5"], H["4"],
                (FrameRange(40, 60),), proof, (), (), (),
            ))


class P2SchemaTests(unittest.TestCase):
    def test_p2_schemas_are_closed_and_cover_emitted_lock_keys(self) -> None:
        root = Path(__file__).resolve().parents[3] / "schemas" / "producer"
        names = (
            "positive-rational-v1.schema.json",
            "picture-lock-v1.schema.json",
            "picture-lock-supersession-v1.schema.json",
            "caption-repair-revalidation-v1.schema.json",
            "cut-restore-speech-v1.schema.json",
            "cut-repair-fragment-receipt-v1.schema.json",
            "cut-repair-composite-receipt-v1.schema.json",
        )
        schemas = {}
        for name in names:
            with (root / name).open(encoding="utf-8") as handle:
                schemas[name] = json.load(handle)
            schema = schemas[name]
            self.assertTrue(
                schema.get("additionalProperties") is False
                or schema.get("unevaluatedProperties") is False)
        lock, _ = mint_picture_lock(_lock_input())
        schema = schemas["picture-lock-v1.schema.json"]
        self.assertTrue(set(schema["required"]).issubset(lock))
        self.assertTrue(set(lock).issubset(schema["properties"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

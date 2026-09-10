"""Actual source replay to body wire tests with explicitly inert whole-media leaves.

No whole-body decode, listening, rendering or approval is performed here. The
original source/consumption readers and new-only receipt bytes are real; their
initial source/pipeline and packet subprocess TEST leaves are fixture-declared.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import copy, deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _body_source_color_work_fixture import BodySourceColorWorkFixture
from cut_preview_io import digest, file_hash, write_new
from guided_body_media import _receipt
from guided_body_read import BodyReadAuthority, _identity, read_body_record, read_result
from guided_body_source_color_result import (READBACK_SCOPE, body_source_result_fields,
                                            recheck_body_source_result)
from guided_body_work import replay_body_source_color


class BodySourceColorResultTests(unittest.TestCase):
    """An actual completed private replay is distinct from a structurally valid DTO."""

    def setUp(self) -> None:
        """Keep original body time deterministic; source and receipt files stay TEST-only."""
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        wall = int(datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp() * 1000) + 63_000
        self.stack.enter_context(patch("time.monotonic", return_value=1000.0))
        self.stack.enter_context(patch("time.time_ns", return_value=wall * 1_000_000))
        self.f = BodySourceColorWorkFixture()
        self.addCleanup(self.f.cleanup)
        self.leaves = self.f.leaves()
        self.addCleanup(self.leaves.close)
        self.work = self.f.work()

    def _receipt(self) -> dict:
        """Publish actual source fields beside deliberately unqualified TEST media data."""
        owner = SimpleNamespace(evidence=[], resolved_clips=(), composition={"TEST": "not rendered"}, caption_screen=None)
        return _receipt(self.work, owner, ({"programDeliveryReceipt": {"TEST": "not delivered"}}, {"TEST": "not decoded"}))

    def _held(self, record: dict) -> BodyReadAuthority:
        """Use actual raw completion SHA and unchanged schema1 worker-entry identity."""
        invocation, root = self.f.control.invocation, self.f.control.root
        write_new(root / "body-worker-entry.json", {"schemaVersion": 1, "kind": "guided-body-worker-entry",
            "activationPath": str(invocation.activation_path), "activationSha256": invocation.activation_sha256,
            "inputSha256": invocation.input_sha256})
        return BodyReadAuthority(invocation, file_hash(root / "body-result.json"), record["receiptHash"])

    def test_actual_replay_fields_survive_exact_new_receipt_and_external_raw_hold(self) -> None:
        """Only completed actual readers produce hashes; unrelated TEST media remains inert."""
        replay_body_source_color(self.work)
        record = self._receipt()
        _identity(record, self.f.control)
        self.assertEqual(read_body_record(self.f.control.root, self._held(record)), record)
        self.assertEqual(recheck_body_source_result(record, self.work), body_source_result_fields(self.work))
        self.assertEqual(record["schemaVersion"], 2)
        self.assertEqual(record["sourceColorReadback"]["observationRecordHash"], digest(self.f.section))
        self.assertEqual(record["sourceColorReadback"]["consumptionRecordHash"], digest(self.f.picture.consumed))
        self.assertFalse(record["sourceColorReadback"]["colorQualified"])
        self.assertFalse(record["bodyApproved"])

    def test_unfinished_or_copied_work_cannot_publish_receipt(self) -> None:
        """The file remains absent when private actual replay authority is missing."""
        self.assertRaisesRegex(RuntimeError, "incomplete", self._receipt)
        self.assertFalse((self.f.control.root / "body-result.json").exists())
        replay_body_source_color(self.work)
        self.assertRaises(RuntimeError, body_source_result_fields, copy(self.work))

    def test_self_reported_hashes_do_not_pass_actual_replay_join(self) -> None:
        """Valid SHA syntax is not proof that either original reader produced it."""
        replay_body_source_color(self.work)
        record = self._receipt()
        for key in ("observationRecordHash", "consumptionRecordHash"):
            row = deepcopy(record)
            row["sourceColorReadback"][key] = "0" * 64
            _identity(row, self.f.control)
            self.assertRaisesRegex(RuntimeError, "actual original replay", recheck_body_source_result, row, self.work)

    def test_closed_source_flags_original_refs_and_version_reject_mutations(self) -> None:
        """Detached receipt edits cannot grant grading or substitute another original input."""
        replay_body_source_color(self.work)
        record = self._receipt()
        faults = [{"schemaVersion": 1}, {"sourceColorReplay": {}}, {"sourceColorReadback": {}}]
        for flag in ("colorQualified", "gradeApplied", "gamutMeasured", "bodyApproved", "deliveryApproved"):
            faults.append({"sourceColorReadback": {**record["sourceColorReadback"], flag: True}})
        for changes in faults:
            with self.subTest(changes=changes):
                self.assertRaises((RuntimeError, ValueError), _identity, {**record, **changes}, self.f.control)
        row = deepcopy(record)
        row["sourceColorReadback"]["sourceColorEvidence"]["sha256"] = "0" * 64
        self.assertRaises((RuntimeError, ValueError), _identity, row, self.f.control)

    def test_missing_duplicate_or_reordered_source_work_stages_reject(self) -> None:
        """Raw worker receipt must retain both actual source phases exactly once."""
        replay_body_source_color(self.work)
        record = self._receipt()
        stages = record["stages"]
        for changed in ([], stages[:1], list(reversed(stages)), stages + stages[:1]):
            self.assertRaises(RuntimeError, _identity, {**record, "stages": changed}, self.f.control)

    def test_readback_replays_two_sibling_groups_on_one_new_bound_read_clock(self) -> None:
        """Real replay/wire route; whole base, graphics, media and AV-final leaves are TEST-only."""
        replay_body_source_color(self.work)
        record = self._receipt()
        held = self._held(record)
        with ExitStack() as leaves:
            leaves.enter_context(patch("guided_body_inputs.verify_runtime_controls"))
            for name in ("read_body_preparation", "_graphics", "_media", "_unchanged"):
                leaves.enter_context(patch("guided_body_read." + name))
            result = read_result(self.f.control.root, held, 300)
        self.assertEqual(result["schemaVersion"], 2)
        self.assertEqual(result["scope"], READBACK_SCOPE)
        self.assertEqual(result["sourceColorReadback"], record["sourceColorReadback"])
        self.assertEqual([row["stage"] for row in result["stages"]], ["body-read-control", "body-read-current-inputs",
            "body-read-held-result", "body-read-current-pipeline", "body-original-source-color-observations",
            "body-original-base-picture-consumption", "body-read-whole-base-master", "body-read-all-graphics",
            "body-read-final-media-and-qc", "body-read-final-revalidation"])
        self.assertFalse(result["bodyApproved"])

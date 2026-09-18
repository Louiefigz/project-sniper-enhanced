"""Body lifecycle fault tests with TEST metadata only; no media or approval."""
from __future__ import annotations

import copy
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from _guided_body_control_fixture import control_fixture
from cut_preview_io import bound_json, digest, file_hash, write_new
from guided_body_cleanup import cleanup
from guided_body_claim import body_registration_intent, body_resource_claim
from guided_body_execution import body_clock
from guided_body_inputs import read_body_control
from guided_body_media import _assemble, _receipt, run
from guided_body_read import BodyReadAuthority, _identity, read_body_record


class GuidedBodyLifecycleTests(unittest.TestCase):
    """Actual receipt/failure files prove no-repeat or orphan-selection boundaries."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.invocation, self.output = control_fixture(self.root, time.time_ns() // 1_000_000 - 63_000)
        patch("guided_body_inputs.verify_runtime_controls").start()
        patch("guided_body_claim.verify_runtime_controls").start()
        patch("guided_body_media.body_source_result_fields", return_value={"schemaVersion": 1}).start()
        self.addCleanup(patch.stopall)
        self.control = read_body_control(self.invocation, self.output)

    def _work(self) -> SimpleNamespace:
        return SimpleNamespace(control=self.control, clock=body_clock(10), guard=Mock(),
            pipeline={"TEST": "not executed"}, workload={"TEST": "not admitted"}, templates={"TEST": "not inspected"})

    def _record(self, work: SimpleNamespace | None = None) -> dict:
        owner = SimpleNamespace(evidence=[], resolved_clips=(), composition={"TEST": "not rendered"}, caption_screen=None)
        selected = work or self._work()
        selected.clock.events.append({"stage": "TEST-not-media", "status": "complete", "elapsedMs": 0})
        return _receipt(selected, owner, ({"programDeliveryReceipt": {"TEST": "not delivered"}}, {"TEST": "not decoded"}))

    def _held(self, record: dict) -> BodyReadAuthority:
        write_new(self.output / "body-worker-entry.json", {"schemaVersion": 1, "kind": "guided-body-worker-entry",
            "activationPath": str(self.invocation.activation_path), "activationSha256": self.invocation.activation_sha256,
            "inputSha256": self.invocation.input_sha256})
        return BodyReadAuthority(self.invocation, file_hash(self.output / "body-result.json"), record["receiptHash"])

    def test_exact_receipt_reads_metadata_but_does_not_assert_media_pass(self) -> None:
        record = self._record()
        held = self._held(record)
        self.assertEqual(read_body_record(self.output, held), record)
        _identity(record, self.control)
        self.assertFalse(record["bodyApproved"])
        self.assertFalse(record["deliveryApproved"])

    def test_failure_marker_blocks_even_same_receipt_and_matching_entry(self) -> None:
        record = self._record()
        held = self._held(record)
        write_new(self.output / "body-failed.json", {"TEST": "interrupted after receipt"})
        with self.assertRaisesRegex(RuntimeError, "orphan"):
            read_body_record(self.output, held)

    def test_no_actual_entry_or_changed_external_raw_hash_blocks(self) -> None:
        record = self._record()
        held = BodyReadAuthority(self.invocation, file_hash(self.output / "body-result.json"), record["receiptHash"])
        with self.assertRaises(FileNotFoundError):
            read_body_record(self.output, held)
        held = self._held(record)
        path = self.output / "body-result.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(RuntimeError, "hash changed"):
            read_body_record(self.output, held)

    def test_identity_rejects_resealed_approval_scope_invocation_and_failed_stages(self) -> None:
        original = self._record()
        for key, value in (("bodyApproved", True), ("deliveryApproved", 0), ("executionId", "TEST-other"),
                           ("executionActivationSha256", "0" * 64), ("references", {}), ("unknown", True),
                           ("stages", [{"stage": "TEST", "status": "failed"}])):
            row = copy.deepcopy(original)
            row[key] = value
            row["receiptHash"] = digest({name: item for name, item in row.items() if name != "receiptHash"})
            with self.subTest(key=key):
                with self.assertRaises(RuntimeError):
                    _identity(row, self.control)

    def test_receipt_is_new_only_and_postwrite_deadline_rejects_success(self) -> None:
        work = self._work()
        work.guard.side_effect = [None, RuntimeError("TEST expired after persistence")]
        with self.assertRaisesRegex(RuntimeError, "expired"):
            self._record(work)
        self.assertTrue((self.output / "body-result.json").exists())
        with self.assertRaises(FileExistsError):
            self._record()

    def test_run_retains_failure_and_never_restarts_same_worker(self) -> None:
        work = self._work()
        read = SimpleNamespace(inputs=object(), source_color_entry=None)
        with patch("guided_body_media.read_body_inputs", return_value=read), \
                patch("guided_body_media.prepare_body_work", return_value=work), \
                patch("guided_body_media.replay_body_source_color"), \
                patch("guided_body_media._execute", side_effect=RuntimeError("TEST worker stopped")) as execute:
            with self.assertRaisesRegex(RuntimeError, "worker stopped"):
                run(self.invocation, self.output, 10)
            with self.assertRaisesRegex(RuntimeError, "new empty"):
                run(self.invocation, self.output, 10)
        execute.assert_called_once()
        failure = bound_json(self.output / "body-failed.json")
        self.assertEqual(failure["status"], "failed")
        self.assertFalse(failure["deliveryApproved"])
        self.assertGreaterEqual(failure["elapsedMs"], 0)

    def test_assembly_exception_never_calls_fallback_and_records_failed_elapsed(self) -> None:
        work, owner = self._work(), SimpleNamespace(composition=None, resolved_clips=None)
        with patch("guided_body_media._job", return_value=object()), \
                patch("guided_body_media.assemble", side_effect=RuntimeError("TEST render failed")) as assemble:
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                _assemble(work, owner)
        assemble.assert_called_once()
        self.assertEqual(work.clock.events[-1]["status"], "failed")
        self.assertGreaterEqual(work.clock.events[-1]["elapsedMs"], 0)

    def test_assembly_missing_or_changed_composition_cannot_return_success(self) -> None:
        work = self._work()
        owner = SimpleNamespace(composition={"TEST": "actual hook"}, resolved_clips=())
        with patch("guided_body_media._job", return_value=object()), \
                patch("guided_body_media.assemble", return_value={"ownedCompositionEvidence": {"TEST": "different"}}):
            with self.assertRaisesRegex(RuntimeError, "omitted"):
                _assemble(work, owner)
        self.assertEqual(work.clock.events[-1]["status"], "failed")

    def test_cleanup_without_healthy_result_or_source_is_metadata_only(self) -> None:
        for ref in self.control.value["references"].values():
            Path(ref["path"]).unlink()
        result = cleanup(self.invocation, self.output, 10)
        self.assertTrue(result["cleanupVerified"])
        self.assertEqual(len(result["graphics"]), 12)
        self.assertTrue(all(row["state"] == "not-initialized" for row in result["graphics"]))
        self.assertFalse(result["bodyApproved"])

    def test_cleanup_armed_missing_ledger_is_unknown_not_safe_absence(self) -> None:
        attempt = self.output / "graphics/attempts/graphic-0"
        attempt.mkdir(parents=True, mode=0o700)
        claim = body_resource_claim(self.control)
        write_new(attempt / "registration-intent.json", body_registration_intent(claim, 0))
        with self.assertRaisesRegex(RuntimeError, "UNKNOWN"):
            cleanup(self.invocation, self.output, 10)


if __name__ == "__main__":
    unittest.main()

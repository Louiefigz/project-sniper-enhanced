"""Explicit schema2 orchestration tests; all file/native/proof leaves are TEST stubs.

These tests establish dispatch, original cutoff and required phase ordering.
They do not qualify a source, cleanup, rendered media or audiovisual quality.
"""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import guided_opening_read as legacy
import guided_source_color_read as reader
from guided_source_color_read_transport import SourceColorReadTransport

STAGES = ["held-result", "held-claim", "current-input-and-sources", "exact-profile-and-frames",
          "current-code-and-tools", "source-color-original-observation-replay", "held-whole-master-and-excerpts",
          "source-color-base-consumption-readback", "exact-graphic-artifacts", "actual-range-media-readback",
          "final-source-result-recheck"]


class SourceColorReadDispatchTests(unittest.TestCase):
    """No TEST success may be confused with actual cold evidence or native verification."""

    def setUp(self) -> None:
        """Create only inert typed transport and a virtual original timing seam."""
        self.paths = (Path("/TEST/input.json"), Path("/TEST/media-output"))
        self.held = legacy.ReadAuthority("a" * 64, Path("/TEST/claim.json"), "b" * 64, "c" * 64, "d" * 64)
        self.transport = SourceColorReadTransport(Path("/TEST/source-color/input.json"), "e" * 64,
                                                  Path("/TEST/cleanup/reservation.json"), "f" * 64)
        self.now, self.calls, self.final_calls = 1000.0, [], 0
        self.inputs = SimpleNamespace(value={"executionId": "TEST-execution", "executionInputHash": "1" * 64})
        self.record = {"schemaVersion": 2, "sourceColorEvidence": {"path": "/TEST/source-color-evidence.json", "sha256": "2" * 64,
                                               "sizeBytes": 1, "receiptHash": "3" * 64}}
        self.selection = SimpleNamespace(master=SimpleNamespace(source_bus=SimpleNamespace(admission=SimpleNamespace(tools={}))))

    def scope(self, inputs: object, record: dict, controls: tuple, transport: object) -> object:
        """Explicit proof fixture: not a SourceColorReadScope or an authenticated source."""
        self.assertIs(transport, self.transport)
        self.scope_value = SimpleNamespace(inputs=inputs, record=record, controls=controls, pipeline={},
            replay_observations=lambda: self.calls.append("observations"),
            replay_consumption=lambda: self.calls.append("consumption"), final_check=self.final_check)
        return self.scope_value

    def final_check(self) -> None:
        """Record only a TEST scope callback, never actual file/native verification."""
        self.final_calls += 1
        self.calls.append("final")

    def leaves(self, stack: ExitStack) -> None:
        """Replace every file/native/identity leaf, preserving the real orchestrator clock/order."""
        stack.enter_context(patch("time.monotonic", side_effect=lambda: self.now))
        factory = stack.enter_context(patch.object(reader, "SourceColorReadScope", side_effect=self.scope))
        factory.replay_observations.side_effect = lambda scope: scope.replay_observations()
        factory.replay_consumption.side_effect = lambda scope: scope.replay_consumption()
        factory.final_check.side_effect = lambda scope: scope.final_check()
        stack.enter_context(patch.object(reader, "capture_source_color_read_entry", return_value=object()))
        stack.enter_context(patch.object(reader, "assert_source_color_read_entry", return_value=None))
        values = {"_record": self.record, "read_execution_claim_metadata": object(), "read_current_inputs": self.inputs,
                  "_identity": None, "executable_frames": [], "_full_program": (self.selection, {}),
                  "read_graphics": None, "_read_picture_ranges": None, "_unchanged": None}
        for name, value in values.items():
            stack.enter_context(patch.object(reader, name, return_value=value))

    def run_read(self) -> dict:
        """Exercise the real explicit schema2 entry and single local remainder."""
        return reader.read_source_color_result(self.paths, self.held, 120, self.transport)

    def test_all_eleven_stages_and_false_approval_are_required(self) -> None:
        """Keep old whole-master/graphic/AV stages alongside the two new proof stages."""
        with ExitStack() as stack:
            self.leaves(stack)
            value = self.run_read()
        self.assertEqual([row["stage"] for row in value["stages"]], STAGES)
        self.assertEqual(value["schemaVersion"], 2)
        self.assertEqual(value["sourceColorEvidence"], self.record["sourceColorEvidence"])
        self.assertIsNot(value["sourceColorEvidence"], self.record["sourceColorEvidence"])
        self.assertEqual(self.calls, ["observations", "consumption", "final", "final"])
        self.assertTrue(value["sourceColorRecordsReplayed"])
        for key in ("gamutMeasured", "gradeApplied", "colorQualified", "openingApproved", "deliveryApproved"):
            self.assertIs(value[key], False)

    def test_missing_transport_refuses_before_clock_or_file_work(self) -> None:
        """A caller cannot silently borrow schema2 behavior from a legacy read."""
        with patch.object(reader, "opening_clock") as clock, patch.object(reader, "_record") as record:
            self.assertRaises(ValueError, reader.read_source_color_result, self.paths, self.held, 120, None)
        clock.assert_not_called()
        record.assert_not_called()

    def test_schema1_with_new_transport_refuses_before_claim_or_source_work(self) -> None:
        """Explicit cold-color flags never upgrade a legacy completion or trigger source admission."""
        self.record["schemaVersion"] = 1
        with ExitStack() as stack:
            self.leaves(stack)
            claim = stack.enter_context(patch.object(reader, "read_execution_claim_metadata"))
            sources = stack.enter_context(patch.object(reader, "read_current_inputs"))
            self.assertRaisesRegex(RuntimeError, "schema2", self.run_read)
        claim.assert_not_called()
        sources.assert_not_called()

    def test_original_receipt_authority_changed_by_early_read_cannot_be_adopted(self) -> None:
        """Mutate only the TEST ReadAuthority object, never an actual file."""
        def changed(*args: object) -> dict:
            """Simulate the first control-read callback changing later held authority."""
            object.__setattr__(self.held, "receipt_sha256", "9" * 64)
            return self.record
        with ExitStack() as stack:
            self.leaves(stack)
            stack.enter_context(patch.object(reader, "_record", side_effect=changed))
            self.assertRaisesRegex(RuntimeError, "original invocation", self.run_read)

    def test_actual_range_failure_is_not_hidden_by_successful_source_phases(self) -> None:
        """An AV failure remains fatal even after both TEST source phases returned."""
        with ExitStack() as stack:
            self.leaves(stack)
            stack.enter_context(patch.object(reader, "_read_picture_ranges", side_effect=RuntimeError("TEST AV failed")))
            self.assertRaisesRegex(RuntimeError, "AV failed", self.run_read)
        self.assertEqual(self.calls, ["observations", "consumption"])

    def test_final_original_deadline_expiry_refuses_success(self) -> None:
        """The last TEST guard cannot extend the already captured read cutoff."""
        actual = self.final_check
        def expired() -> None:
            """Expire only the virtual clock after the second final callback."""
            actual()
            if self.final_calls == 2:
                self.now = 1120.0
        with ExitStack() as stack:
            self.leaves(stack)
            stack.enter_context(patch.object(self, "final_check", side_effect=expired))
            self.assertRaisesRegex(RuntimeError, "deadline", self.run_read)

    def test_final_callback_mutation_of_detached_result_is_refused(self) -> None:
        """Retain the actual returned JSON object before the last TEST scope callback."""
        actual, final = reader._result, self.final_check
        retained = []
        def result(*args: object) -> dict:
            """Hold only this TEST result so the final callback can change it."""
            value = actual(*args)
            retained.append(value)
            return value
        def changed() -> None:
            """Do not mutate original sources or production implementation files."""
            final()
            if retained:
                retained[0]["openingApproved"] = True
        with ExitStack() as stack:
            self.leaves(stack)
            stack.enter_context(patch.object(reader, "_result", side_effect=result))
            stack.enter_context(patch.object(self, "final_check", side_effect=changed))
            self.assertRaisesRegex(RuntimeError, "last callback", self.run_read)

    def test_legacy_selection_preserves_three_argument_dispatch(self) -> None:
        """No optional references retain the actual old entrypoint contract."""
        with patch.object(legacy, "read_result", return_value={"TEST": "legacy"}) as old, \
                patch.object(reader, "read_source_color_result") as new:
            value = legacy._selected_read(self.paths, self.held, 120, None)
        old.assert_called_once_with(self.paths, self.held, 120)
        new.assert_not_called()
        self.assertEqual(value, {"TEST": "legacy"})

    def test_cli_partial_quartet_rejects_before_either_reader(self) -> None:
        """A partial new CLI request cannot fall through to a legacy read."""
        argv = ["read", *map(str, self.paths), "--input-sha256", "a" * 64, "--execution-claim", "/TEST/claim.json",
                "--execution-claim-sha256", "b" * 64, "--receipt-sha256", "c" * 64, "--receipt-hash", "d" * 64,
                "--timeout-seconds", "120", "--source-color-input", "/TEST/source-color/input.json"]
        with patch("sys.argv", argv), patch.object(legacy, "_selected_read") as selected, \
                redirect_stderr(StringIO()), redirect_stdout(StringIO()):
            self.assertEqual(legacy.main(), 1)
        selected.assert_not_called()


if __name__ == "__main__":
    unittest.main()

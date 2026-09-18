"""Actual bounded TEST control-file reads; no source, runtime or approval claim."""
from __future__ import annotations

import copy
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _guided_body_control_fixture import control_fixture
from cut_preview_io import bound_json, file_hash
from guided_body_budget import bind_body_budget
from guided_body_execution import assert_body_files, body_clock
from guided_body_inputs import read_body_control


class GuidedBodyControlTests(unittest.TestCase):
    """Only runtime admission is TEST-stubbed; actual fixed-path bytes are read."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.origin = time.time_ns() // 1_000_000 - 63_000
        self.invocation, self.output = control_fixture(self.root, self.origin)
        self.runtime = patch("guided_body_inputs.verify_runtime_controls").start()
        self.addCleanup(patch.stopall)

    def test_full_control_keeps_original_ids_and_nonexecutable_admission(self) -> None:
        result = read_body_control(self.invocation, self.output)
        self.assertNotEqual(result.value["executionId"], result.documents["openingInput"]["executionId"])
        self.assertFalse(result.documents["admissionClaim"]["executable"])
        self.assertEqual(result.value["selectedGraphicOrders"], list(range(12)))
        self.runtime.assert_called_once()
        assert_body_files(result.held_files, body_clock(10))

    def test_external_input_or_activation_hash_cannot_be_recomputed_from_disk(self) -> None:
        for field in ("input_sha256", "activation_sha256"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(RuntimeError, "held identity"):
                    read_body_control(replace(self.invocation, **{field: "0" * 64}), self.output)
        self.runtime.assert_not_called()

    def test_input_cannot_move_outside_exact_execution_topology(self) -> None:
        path = self.invocation.input_path
        other = path.parent / "different-name.json"
        other.write_bytes(path.read_bytes())
        with self.assertRaises(RuntimeError):
            read_body_control(replace(self.invocation, input_path=other), self.output)
        self.runtime.assert_not_called()

    def test_declared_reference_mutation_rejected_before_runtime(self) -> None:
        row = bound_json(self.invocation.input_path)
        path = Path(row["references"]["heldInput"]["path"])
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(RuntimeError, "held identity"):
            read_body_control(self.invocation, self.output)
        self.runtime.assert_not_called()

    def test_control_fifo_hardlink_and_symlink_do_not_reach_runtime(self) -> None:
        original = self.invocation.activation_path
        raw = original.read_bytes()
        for kind in ("fifo", "symlink", "hardlink"):
            original.unlink()
            other = original.parent / ("TEST-" + kind)
            if kind == "fifo":
                os.mkfifo(original)
            else:
                other.write_bytes(raw)
                (original.symlink_to(other) if kind == "symlink" else os.link(other, original))
            with self.subTest(kind=kind):
                with self.assertRaises((OSError, RuntimeError)):
                    read_body_control(self.invocation, self.output)
        self.runtime.assert_not_called()

    def test_original_budget_binds_once_and_cannot_reset_parent_remainder(self) -> None:
        control = read_body_control(self.invocation, self.output)
        clock = body_clock(10)
        end = clock.end
        bind_body_budget(control, clock)
        self.assertLessEqual(clock.end, end)
        self.assertGreater(clock.remaining(), 0)
        with self.assertRaisesRegex(RuntimeError, "rebound"):
            bind_body_budget(control, clock)

    def test_budget_mutations_do_not_create_new_or_negative_allowance(self) -> None:
        original = read_body_control(self.invocation, self.output)
        cases = [("budgetAdmission", "admitted", False), ("budgetAdmission", "excludedUserWaitMs", 0),
                 ("budgetAdmission", "elapsedRequestWallMs", 0), ("budgetPrecommit", "elapsedMs", True),
                 ("budgetPrecommit", "elapsedMs", 0), ("budgetPrecommit", "remainingMs", 3_300_000)]
        for document, field, value in cases:
            docs = copy.deepcopy(original.documents)
            docs[document][field] = value
            with self.subTest(document=document, field=field):
                with self.assertRaises(RuntimeError):
                    bind_body_budget(replace(original, documents=docs), body_clock(10))

    def test_stalled_or_rolled_back_wall_does_not_extend_actual_entry_time(self) -> None:
        control = read_body_control(self.invocation, self.output)
        clock = body_clock(10)
        now = time.time_ns()
        with patch("guided_body_execution.time.time_ns", return_value=now):
            bind_body_budget(control, clock)
            previous = clock.remaining()
        with patch("guided_body_execution.time.time_ns", return_value=now - 1_000_000):
            with self.assertRaisesRegex(RuntimeError, "rolled back"):
                clock.remaining()
        with self.assertRaises(RuntimeError):
            clock.remaining()
        self.assertLess(previous, 10)


if __name__ == "__main__":
    unittest.main()

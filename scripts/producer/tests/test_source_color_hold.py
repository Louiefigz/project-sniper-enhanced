"""Retained source preparation checks; inert TEST sources and no media processes."""
from __future__ import annotations

import os
import stat
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _source_color_preparation_fixture import SourceColorPreparationFixture
from guided_source_color_hold import HeldSourceColorPreparation, hold_source_color_preparation


class SourceColorHoldTests(unittest.TestCase):
    """Prepared data remains tied to the actual original complete source capture."""

    def setUp(self) -> None:
        """Use a single original fake clock and explicitly owned inert fixture files."""
        self.clock = [1000.0]
        clock = patch.object(time, "monotonic", side_effect=lambda: self.clock[0])
        clock.start()
        self.addCleanup(clock.stop)
        self.fixture = SourceColorPreparationFixture()
        self.addCleanup(self.fixture.cleanup)

    def hold(self) -> HeldSourceColorPreparation:
        """Exercise the actual full preparation and lifetime constructor."""
        fixture = self.fixture
        return hold_source_color_preparation(fixture.inputs, fixture.declarations, fixture.context)

    def _append(self, path: Path) -> None:
        """Fault only a named canonical TEST-owned single-link file, never a dependency."""
        root = Path(self.fixture.temporary.name).resolve(strict=True)
        if root != self.fixture.root or not path.is_relative_to(root) or path.resolve(strict=True) != path:
            raise RuntimeError("fault target outside exact TEST root")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise RuntimeError("fault target not TEST-owned regular file")
        path.write_bytes(path.read_bytes() + b"\nTEST held preparation fault\n")

    def test_hold_uses_same_capture_objects_in_first_occurrence_order(self) -> None:
        """A repeated source cut is one prepared source, not another decode request."""
        held = self.hold()
        self.assertIs(held.context, self.fixture.context)
        self.assertIs(held.inputs, self.fixture.inputs)
        self.assertEqual([row.binding.source_id for row in held.jobs], ["raw-b", "raw-a"])
        original = {row.path: row for row in self.fixture.inputs.verified_media.snapshots}
        for row in held.jobs:
            self.assertIs(row.source, original[row.source.path])
        held.assert_current()
        self.assertIs(held.executable, False)
        self.assertIs(held.grade_applicable, False)
        self.assertIs(held.delivery_approved, False)
        self.assertFalse((self.fixture.producer / ".sniper-grade-observations").exists())

    def test_no_public_reconstruction_from_prepared_data(self) -> None:
        """The holding API requires the original successful source preparation read."""
        with self.assertRaisesRegex(TypeError, "requires hold_source_color_preparation"):
            HeldSourceColorPreparation()

    def test_later_reads_use_stats_not_source_or_receipt_rehashes(self) -> None:
        """Repeated later guards do not introduce an all-media hashing multiplier."""
        held = self.hold()
        with patch("guided_source_color_preparation.read_bytes", side_effect=AssertionError("no byte rereads")), \
                patch("color.grade_project_authority.observe_project", side_effect=AssertionError("no decode")):
            held.assert_current()
            held.assert_current()

    def test_actual_guard_loss_after_preparation_rejects(self) -> None:
        """A completed preparation does not persist original ownership indefinitely."""
        held = self.hold()
        self.fixture.guard.side_effect = RuntimeError("TEST persistent source/tool/project ownership lost")
        with self.assertRaisesRegex(RuntimeError, "ownership lost"):
            held.assert_current()

    def test_original_expiry_rejects_without_callback_or_refreshed_clock(self) -> None:
        """Time elapsed in another stage still consumes the original overall budget."""
        held = self.hold()
        self.fixture.guard.reset_mock()
        self.clock[0] = 1300.0
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            held.assert_current()
        self.fixture.guard.assert_not_called()

    def test_longer_context_deadline_is_not_adopted(self) -> None:
        """A replacement allowance cannot make a previously prepared source current."""
        held = self.hold()
        object.__setattr__(self.fixture.context, "deadline", 1600.0)
        with self.assertRaisesRegex(RuntimeError, "original input/context changed"):
            held.assert_current()

    def test_equal_valued_context_clone_is_not_the_original(self) -> None:
        """Structural equality does not replace the caller that held preparation."""
        held = self.hold()
        object.__setattr__(held, "context", replace(held.context))
        with self.assertRaisesRegex(RuntimeError, "original lifetime changed"):
            held.assert_current()

    def test_equal_valued_source_clone_is_not_the_hash_pass_identity(self) -> None:
        """Prepared source rows retain the same actual verified source object."""
        held = self.hold()
        object.__setattr__(held.jobs[0], "source", replace(held.jobs[0].source))
        with self.assertRaisesRegex(RuntimeError, "original references or metadata changed"):
            held.assert_current()

    def test_row_numeric_type_change_is_not_equal_typed_metadata(self) -> None:
        """A frame count becoming a floating point number cannot pass by equality."""
        held = self.hold()
        binding = held.jobs[0].binding
        object.__setattr__(binding, "frame_count", float(binding.frame_count))
        with self.assertRaisesRegex(RuntimeError, "original references or metadata changed"):
            held.assert_current()

    def test_row_metadata_and_false_flags_remain_bound(self) -> None:
        """Prepared data cannot be promoted into grade applicability or execution."""
        held = self.hold()
        object.__setattr__(held.jobs[0], "metadata_json", b"{}")
        with self.assertRaisesRegex(RuntimeError, "original references or metadata changed"):
            held.assert_current()
        held = self.hold()
        object.__setattr__(held, "executable", True)
        with self.assertRaisesRegex(RuntimeError, "original references or metadata changed"):
            held.assert_current()

    def test_original_declaration_mutation_after_return_rejects(self) -> None:
        """Later phases cannot reuse preparation after the operator's declaration moves."""
        held = self.hold()
        self.fixture.declarations["raw-a"]["declaration"]["historyState"] = "unknown"
        with self.assertRaisesRegex(RuntimeError, "original input/context changed"):
            held.assert_current()

    def test_callback_mutation_is_checked_after_the_actual_original_guard(self) -> None:
        """The final callback cannot change an already prepared second source row."""
        held = self.hold()
        self.fixture.guard.side_effect = lambda: object.__setattr__(held.jobs[1], "delivery_approved", True)
        with self.assertRaisesRegex(RuntimeError, "original references or metadata changed"):
            held.assert_current()

    def test_callback_expiry_remains_original_expiry(self) -> None:
        """The final retained-read callback has no independent success allowance."""
        held = self.hold()
        self.fixture.guard.side_effect = lambda: self.clock.__setitem__(0, 1300.0)
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            held.assert_current()

    def test_source_changes_after_preparation_reject_without_rehash(self) -> None:
        """Original source stat changes invalidate the capture, even on later reads."""
        held = self.hold()
        self._append(Path(held.jobs[0].source.path))
        with self.assertRaisesRegex(RuntimeError, "snapshot identity changed"):
            held.assert_current()

    def test_parent_changes_after_preparation_reject(self) -> None:
        """The exact saved project remains part of the source declaration binding."""
        held = self.hold()
        self._append(self.fixture.root / "project.json")
        with self.assertRaisesRegex(RuntimeError, "held parent/receipt changed"):
            held.assert_current()

    def test_private_read_clock_cannot_be_rebound(self) -> None:
        """Even direct private metadata replacement cannot extend the held lifetime."""
        held = self.hold()
        object.__setattr__(held._read, "deadline", 1600.0)
        with self.assertRaisesRegex(RuntimeError, "original references or metadata changed"):
            held.assert_current()

    def test_lifetime_constructor_final_callback_withholds_result(self) -> None:
        """The callback after the four preparation guards is still part of the hold."""
        def guard() -> None:
            """Mutate only fixture input metadata at the constructor's final callback."""
            if self.fixture.guard.call_count == 5:
                self.fixture.inputs.value["pipeline"]["TEST"] = "changed after preparation"

        self.fixture.guard.side_effect = guard
        with self.assertRaisesRegex(RuntimeError, "original input/context changed"):
            self.hold()
        self.assertEqual(self.fixture.guard.call_count, 5)

    def test_runtime_remaining_replacement_rejects_before_its_invocation(self) -> None:
        """An unchanged runtime object cannot conceal a changed original clock callback."""
        held = self.hold()
        calls = []
        object.__setattr__(held._read.runtime, "remaining", lambda: calls.append(True) or 999.0)
        with self.assertRaisesRegex(RuntimeError, "original input/context changed"):
            held.assert_current()
        self.assertEqual(calls, [])

    def test_guard_cannot_install_a_later_metadata_mutating_clock_callback(self) -> None:
        """Reject replacement before the source sweep can invoke it after argument checks."""
        held = self.hold()
        calls = []

        def changed_clock() -> float:
            """Mutation is in TEST metadata only; this callback must never be invoked."""
            calls.append(True)
            self.fixture.inputs.value["pipeline"]["TEST"] = "late runtime mutation"
            return 299.0

        self.fixture.guard.side_effect = lambda: object.__setattr__(held._read.runtime, "remaining", changed_clock)
        with self.assertRaisesRegex(RuntimeError, "original input/context changed"):
            held.assert_current()
        self.assertEqual(calls, [])

    def test_final_stat_helper_cannot_move_original_input_metadata(self) -> None:
        """A final pure comparison follows all filesystem helpers before returning current."""
        import guided_source_color_preparation as preparation

        held = self.hold()
        original = preparation.snapshot_stat_identity
        total = len(held._read.files)
        calls = []

        def changed_stat(value: os.stat_result) -> tuple:
            """Wrap the real metadata helper; no actual file is changed."""
            result = original(value)
            calls.append(True)
            if len(calls) == total:
                self.fixture.inputs.value["pipeline"]["TEST"] = "changed after final stat"
            return result

        with patch.object(preparation, "snapshot_stat_identity", side_effect=changed_stat), \
                self.assertRaisesRegex(RuntimeError, "original input/context changed"):
            held.assert_current()

    def test_fault_writer_refuses_actual_production_dependency(self) -> None:
        """A production module path is never an authorized destructive test fixture."""
        import guided_source_color_hold

        with patch.object(Path, "write_bytes") as write, self.assertRaisesRegex(RuntimeError, "exact TEST root"):
            self._append(Path(guided_source_color_hold.__file__).resolve(strict=True))
        write.assert_not_called()

    def test_final_argument_serialization_consumes_original_remaining_time(self) -> None:
        """Expiring while serializing last metadata cannot become successful preparation."""
        import guided_source_color_preparation as preparation

        held = self.hold()
        original = preparation._json
        with patch.object(preparation, "_json", wraps=original) as count:
            held.assert_current()
        total, calls = count.call_count, []

        def expire(value: object, maximum: int = preparation.MAX_SOURCE_SET_BYTES) -> bytes:
            """Complete the real serializer and expire only on its last invocation."""
            result = original(value, maximum)
            calls.append(True)
            if len(calls) == total:
                self.clock[0] = self.fixture.context.deadline
            return result

        with patch.object(preparation, "_json", side_effect=expire), \
                self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            held.assert_current()


if __name__ == "__main__":
    unittest.main()

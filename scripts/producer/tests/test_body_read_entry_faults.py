"""Actual body read entry faults; all AV/native leaves are explicitly inert.

Reuse the root's genuine source replay/result fixture. Fault writes are limited
to its two original private body output records, never sources or tool files.
"""
from __future__ import annotations

from contextlib import ExitStack
import inspect
import os
from pathlib import Path
import stat
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_body_source_color_result as result_fixture
from guided_body_execution import BodyExecutionClock, body_clock
from guided_body_budget import bind_body_budget
from guided_body_read import read_result
from guided_body_read_entry import BodyReadLifetime
from guided_body_work import replay_body_source_color
import guided_body_read as reader


class BodyReadEntryFaultTests(unittest.TestCase):
    """Real receipt/source holders survive first-control and final-clock callbacks."""

    def setUp(self) -> None:
        """Reuse only fixture setup/helpers, not inherited unrelated test methods."""
        result_fixture.BodySourceColorResultTests.setUp(self)
        replay_body_source_color(self.work)
        record = result_fixture.BodySourceColorResultTests._receipt(self)
        self.held = result_fixture.BodySourceColorResultTests._held(self, record)
        self.root = self.f.control.root
        self.allowed = frozenset(self.root / name for name in ("body-result.json", "body-worker-entry.json"))

    def _run(self) -> dict:
        """Keep actual controls/replay/read orchestration; only whole-body AV leaves differ."""
        with ExitStack() as leaves:
            leaves.enter_context(patch("guided_body_inputs.verify_runtime_controls"))
            for name in ("read_body_preparation", "_graphics", "_media", "_unchanged"):
                leaves.enter_context(patch("guided_body_read." + name))
            return read_result(self.root, self.held, 300)

    def _replace(self, name: str) -> None:
        """Same-byte replace only exact canonical owned body result/worker-entry files."""
        target = self.root / name
        self.assertIn(target, self.allowed)
        self.assertEqual(target.resolve(strict=True), target)
        self.assertEqual(target.parent.resolve(strict=True), self.root)
        self.assertTrue(self.root.is_relative_to(self.f.root.resolve(strict=True)))
        info = target.lstat()
        self.assertTrue(stat.S_ISREG(info.st_mode))
        self.assertEqual((info.st_uid, info.st_nlink), (os.getuid(), 1))
        temporary = target.with_name("TEST-body-read-replacement-" + str(uuid4()) + ".json")
        with temporary.open("xb") as stream:
            stream.write(target.read_bytes())
        temporary.chmod(0o600)
        temporary.replace(target)

    def test_final_elapsed_sample_cannot_return_after_original_cutoff(self) -> None:
        """The final real elapsed sample must not turn an expired read into verified."""
        observed = []

        def monotonic() -> float:
            """Advance only the actual read_result final elapsed-expression sample."""
            frame = inspect.currentframe().f_back
            if frame.f_code is reader.read_result.__code__ and "fields" in frame.f_locals:
                observed.append(True)
            return 1400.0 if observed else 1000.0

        try:
            with patch("time.monotonic", monotonic):
                self.assertRaisesRegex(RuntimeError, "deadline|expired", self._run)
        finally:
            self.assertTrue(observed, "TEST final elapsed fault must actually execute")

    def test_first_clock_sample_cannot_extend_original_body_allowance(self) -> None:
        """Capture the newly constructed cutoff before the first phase clock callback."""
        actual, sampled = BodyExecutionClock.remaining, []

        def remaining(clock: BodyExecutionClock) -> float:
            """After the first actual sample, attempt to enlarge that same clock."""
            result = actual(clock)
            if not sampled:
                sampled.append(clock.end)
                clock.end += 1
            return result

        with patch.object(BodyExecutionClock, "remaining", remaining):
            self.assertRaisesRegex(RuntimeError, "original.*clock|cutoff", self._run)
        self.assertEqual(sampled, [1300.0])

    def test_first_clock_callback_cannot_change_raw_receipt_authority(self) -> None:
        """Original request is retained before constructing/sampling any work clock."""
        actual, changed = BodyExecutionClock.remaining, []

        def remaining(clock: BodyExecutionClock) -> float:
            """Mutate only the actual in-memory request after its first real sample."""
            value = actual(clock)
            if not changed:
                changed.append(True)
                object.__setattr__(self.held, "receipt_sha256", "0" * 64)
            return value

        with patch.object(BodyExecutionClock, "remaining", remaining), patch.object(reader, "read_body_control") as control:
            self.assertRaisesRegex(RuntimeError, "original read request", self._run)
        control.assert_not_called()

    def test_first_clock_callback_cannot_replace_original_output_inode(self) -> None:
        """The earliest remaining call must not substitute same-byte output before capture."""
        actual, changed = BodyExecutionClock.remaining, []

        def remaining(clock: BodyExecutionClock) -> float:
            """Replace only the exact owned body-result after its first actual sample."""
            value = actual(clock)
            if not changed:
                changed.append(True)
                self._replace("body-result.json")
            return value

        with patch.object(BodyExecutionClock, "remaining", remaining):
            self.assertRaisesRegex(RuntimeError, "output file identity", self._run)
        self.assertTrue(changed)

    def test_first_control_callback_cannot_replace_result_inode(self) -> None:
        """Both output identities must precede the first original control read."""
        actual = reader.read_body_control

        def control(invocation: object, root: Path) -> object:
            """Only the exact original body output record is substituted."""
            self._replace("body-result.json")
            return actual(invocation, root)

        with patch.object(reader, "read_body_control", side_effect=control):
            self.assertRaisesRegex(RuntimeError, "output file identity", self._run)

    def test_first_control_callback_cannot_replace_worker_entry_inode(self) -> None:
        """The original worker entry cannot be recaptured after control admission."""
        actual = reader.read_body_control

        def control(invocation: object, root: Path) -> object:
            """Only the exact original worker entry record is substituted."""
            self._replace("body-worker-entry.json")
            return actual(invocation, root)

        with patch.object(reader, "read_body_control", side_effect=control):
            self.assertRaisesRegex(RuntimeError, "output file identity", self._run)

    def test_control_return_cannot_replace_original_invocation_path_object(self) -> None:
        """Equal path text does not replace the originally captured invocation field."""
        actual = reader.read_body_control

        def control(invocation: object, root: Path) -> object:
            """Mutate only in-memory caller metadata after actual control admission."""
            value = actual(invocation, root)
            original = invocation.input_path
            replacement = Path(str(original))
            self.assertIsNot(original, replacement)
            object.__setattr__(invocation, "input_path", replacement)
            return value

        with patch.object(reader, "read_body_control", side_effect=control):
            self.assertRaisesRegex(RuntimeError, "original read request", self._run)

    def test_original_output_ancestor_identity_is_retained_before_control(self) -> None:
        """Simulate exact output-parent inode substitution; no directory is mutated."""
        actual_control, actual_stat, armed = reader.read_body_control, Path.lstat, []
        parent = self.root.parent
        self.assertTrue(parent.is_relative_to(self.f.root.resolve(strict=True)))

        def observed(file: Path, *args: object, **kwargs: object) -> os.stat_result:
            """Only one exact fixture ancestor reports a different inode after admission."""
            info = actual_stat(file, *args, **kwargs)
            if file == parent and armed:
                fields = list(info)
                fields[1] += 1
                return os.stat_result(fields)
            return info

        def control(invocation: object, root: Path) -> object:
            """Arm the inode observation after actual control; later source work must stop."""
            value = actual_control(invocation, root)
            armed.append(True)
            return value

        with patch.object(Path, "lstat", observed), patch.object(reader, "read_body_control", side_effect=control):
            self.assertRaisesRegex(RuntimeError, "directory ancestry", self._run)

    def test_bound_clock_watermark_cannot_be_lowered_between_stat_calls(self) -> None:
        """Retain each actual sampled wall watermark, not just the last call's value."""
        hold = BodyReadLifetime(self.root, self.held)
        clock = body_clock(300)
        hold.start_clock(clock)
        hold.capture(clock)
        bind_body_budget(self.f.control, clock)
        hold.bind()
        initial, actual, changed = clock.previous_wall_ms, Path.lstat, []

        def observed(file: Path, *args: object, **kwargs: object) -> os.stat_result:
            """No file writes; lower actual time and watermark after the first sample."""
            info = actual(file, *args, **kwargs)
            if file == self.root / "body-result.json" and not changed:
                changed.append(True)
                clock.previous_wall_ms = initial + 500
            return info

        with patch("time.time_ns", side_effect=lambda: (initial + (500 if changed else 1000)) * 1_000_000), patch.object(Path, "lstat", observed):
            self.assertRaisesRegex(RuntimeError, "watermark.*backwards", hold.check)
        self.assertTrue(changed)

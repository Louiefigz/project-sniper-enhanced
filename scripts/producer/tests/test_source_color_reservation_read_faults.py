"""Named TEST-only raw/parser/lifetime faults; never mutate dependencies or live claims."""
from __future__ import annotations

from copy import copy
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from _source_color_reservation_fixture import SourceColorReservationFixture
import guided_source_color_reservation_read as reader


class SourceColorReservationReadFaultTests(unittest.TestCase):
    """Hold all exact names and original references across cold metadata callbacks."""

    def fixture(self) -> SourceColorReservationFixture:
        """Allocate one distinct original TEST root and virtual deadline per fault."""
        value = SourceColorReservationFixture()
        self.addCleanup(value.close)
        timer = patch("color.deadline.time.monotonic", side_effect=lambda: value.staging.now)
        timer.start()
        self.addCleanup(timer.stop)
        return value

    def test_every_original_file_remains_held_during_final_callback(self) -> None:
        """Same-byte writes to any exact original file are rejected after the guard."""
        for name in ("reservation_path", "claim_path", "input_path"):
            f = self.fixture()
            held, target = f.run(), getattr(f, name)
            f.staging.guard.side_effect = lambda: f.write(target, target.read_bytes())
            with self.assertRaisesRegex(RuntimeError, "file or ancestry changed"):
                held.assert_current()

    def test_duplicate_json_invalid_utf8_and_raw_reservation_overflow_reject(self) -> None:
        """The cold path uses the actual bounded fatal decoder, not a JSON rehydration."""
        for raw in (b'{"jobs":[],"jobs":[]}', b'{"TEST":"\xff"}', b" " * (8 * 1024 ** 2 + 1)):
            f = self.fixture()
            f.reference = (f.reservation_path, f.write(f.reservation_path, raw))
            with self.assertRaises((ValueError, RuntimeError, UnicodeDecodeError)):
                f.run()

    def test_reservation_class_is_additive_but_original_input_remains_128k(self) -> None:
        """Partial cleanup metadata does not widen existing original input byte bounds."""
        f = self.fixture()
        raw = b" " * (129 * 1024) + f.reservation_path.read_bytes()
        f.reference = (f.reservation_path, f.write(f.reservation_path, raw))
        self.assertEqual(f.run().value, f.reservation)
        f.write(f.input_path, b" " * (129 * 1024) + f.input_path.read_bytes())
        with self.assertRaisesRegex(RuntimeError, "exceeds byte limit: [0-9]+ > 131072"):
            f.run()

    def test_aliased_reservation_is_not_opened_and_fault_writer_rejects_dependencies(self) -> None:
        """Only this explicitly named TEST file is replaced with a fixture-local link."""
        f = self.fixture()
        with self.assertRaisesRegex(AssertionError, "exact three files"):
            f.write(Path(__file__), b"TEST must not touch dependencies")
        f.reservation_path.unlink()
        f.reservation_path.symlink_to(f.claim_path)
        with self.assertRaisesRegex(RuntimeError, "private single-link"):
            f.run()
        f.staging.guard.assert_not_called()
        with self.assertRaisesRegex(AssertionError, "regular single-link"):
            f.write(f.reservation_path, b"TEST must not follow aliases")

    def test_cloned_reader_or_changed_original_name_projection_cannot_be_reused(self) -> None:
        """A successful metadata read is not reconstructible from its public fields."""
        f = self.fixture()
        held = f.run()
        with self.assertRaisesRegex(RuntimeError, "held reader identity"):
            copy(held).assert_current()
        object.__setattr__(held, "container_names", tuple(reversed(held.container_names)))
        with self.assertRaisesRegex(RuntimeError, "held reader identity"):
            held.assert_current()

    def test_original_claim_or_guard_swap_is_not_invoked_or_adopted(self) -> None:
        """Cold semantics allow PID changes, not replacing original caller ownership."""
        f = self.fixture()
        f.staging.guard.side_effect = lambda: object.__setattr__(f.context, "opening", replace(f.context.opening))
        with self.assertRaisesRegex(RuntimeError, "original context"):
            f.run()
        f = self.fixture()
        called = []
        f.staging.guard.side_effect = lambda: object.__setattr__(f.context, "guard", lambda: called.append(True))
        with self.assertRaisesRegex(RuntimeError, "original context"):
            f.run()
        self.assertEqual(called, [])

    def test_raw_reservation_size_is_bound_to_actual_captured_bytes(self) -> None:
        """Equal-valued float or changed size cannot replace the actual raw-length fact."""
        f = self.fixture()
        held = f.run()
        for size in (float(held.size_bytes), held.size_bytes + 1):
            object.__setattr__(held, "size_bytes", size)
            with self.assertRaisesRegex(RuntimeError, "held reader identity"):
                held.assert_current()

    def test_late_parser_expiry_and_guard_cancellation_cannot_return_metadata(self) -> None:
        """The caller's same original deadline includes final pure parser work."""
        f, original = self.fixture(), reader.validate_source_color_reservation

        def expire(value: object) -> dict:
            """Advance only the original TEST clock after the real pure parser."""
            result = original(value)
            f.staging.now = f.context.deadline
            return result

        with patch.object(reader, "validate_source_color_reservation", side_effect=expire):
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                f.run()
        f = self.fixture()
        failure = RuntimeError("TEST original ownership cancelled")
        f.staging.guard.side_effect = failure
        with self.assertRaises(RuntimeError) as raised:
            f.run()
        self.assertIs(raised.exception, failure)


if __name__ == "__main__":
    unittest.main()

"""Actual orchestration tail under explicit TEST-only file/native/scope leaves.

These timing/serialization tests reuse the root's inert orchestration fixture;
they are not actual media proof, pipeline admission or source qualification.
Actual registered scope and raw-file regressions live in the adjacent suite.
"""
from __future__ import annotations

from contextlib import ExitStack
import unittest
from unittest.mock import patch

import guided_source_color_read as reader
import test_source_color_read_dispatch as dispatch


class SourceColorReadTailFaultTests(unittest.TestCase):
    """Retain the final actual phase projection through the last arbitrary callback."""

    def setUp(self) -> None:
        """Create the explicitly virtual root fixture without invoking any real tool."""
        self.h = dispatch.SourceColorReadDispatchTests()
        self.h.setUp()

    def test_elapsed_includes_final_guard_tail_not_only_completed_stages(self) -> None:
        """One existing clock charges work after the last timed stage too."""
        final = self.h.final_check

        def delayed() -> None:
            """Advance the original virtual clock only after the result is projected."""
            final()
            if self.h.final_calls == 2:
                self.h.now += 0.25

        with ExitStack() as stack:
            self.h.leaves(stack)
            stack.enter_context(patch.object(self.h, "final_check", side_effect=delayed))
            result = self.h.run_read()
        self.assertEqual(result["elapsedMs"], 250)
        self.assertEqual(sum(row["elapsedMs"] for row in result["stages"]), 0)

    def test_last_callback_cannot_change_original_completed_event_projection(self) -> None:
        """The detached result cannot hide a changed original clock event after copying."""
        final = self.h.final_check

        def changed() -> None:
            """Mutate only the original TEST clock metadata, never a file or deadline."""
            final()
            if self.h.final_calls == 2:
                self.h.scope_value.controls[2].events[0]["status"] = "failed"

        with ExitStack() as stack:
            self.h.leaves(stack)
            stack.enter_context(patch.object(self.h, "final_check", side_effect=changed))
            with self.assertRaises(RuntimeError):
                self.h.run_read()

    def test_missing_stage_cannot_be_projected_as_verified(self) -> None:
        """A stage list is closed coverage evidence, not just a mutable report array."""
        final = self.h.final_check

        def omitted() -> None:
            """Remove a completed TEST event before the final result is constructed."""
            final()
            if self.h.final_calls == 1:
                self.h.scope_value.controls[2].events.pop(0)

        with ExitStack() as stack:
            self.h.leaves(stack)
            stack.enter_context(patch.object(self.h, "final_check", side_effect=omitted))
            with self.assertRaises(RuntimeError):
                self.h.run_read()

    def test_last_returned_elapsed_numeric_type_change_is_not_equal_metadata(self) -> None:
        """Int-to-equal-float replacement must reject even when arithmetic is equal."""
        actual, final, values = reader._result, self.h.final_check, []

        def result(*args: object) -> dict:
            """Retain only the actual returned TEST result for the following fault."""
            value = actual(*args)
            values.append(value)
            return value

        def changed() -> None:
            """Mutate only the already detached final report object."""
            final()
            if values:
                values[0]["elapsedMs"] = float(values[0]["elapsedMs"])

        with ExitStack() as stack:
            self.h.leaves(stack)
            stack.enter_context(patch.object(reader, "_result", side_effect=result))
            stack.enter_context(patch.object(self.h, "final_check", side_effect=changed))
            with self.assertRaisesRegex(RuntimeError, "last callback"):
                self.h.run_read()


if __name__ == "__main__":
    unittest.main()

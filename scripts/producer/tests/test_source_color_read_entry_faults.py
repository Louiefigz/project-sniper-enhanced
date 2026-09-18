"""Original-entry-to-claim-phase continuity, using actual raw metadata reads.

Every mutation targets one of six exact original TEMP controls. No media,
pipeline discovery, source reader or native process is reached by these
negative cases; the former accepted later baseline is the regression target.
"""
from __future__ import annotations

from copy import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from _source_color_read_scope_fixture import ColdReadScopeFixture
import guided_opening_claim as claim
from guided_source_color_read import read_source_color_result
import guided_source_color_read as reader
from guided_source_color_read_entry import assert_source_color_read_entry
from guided_opening_execution import OpeningExecutionClock


class ColdReadEntryFaultTests(unittest.TestCase):
    """A same-byte control replacement must fail before the later source admission."""

    def setUp(self) -> None:
        """Original independent reference bytes exist before the first read clock phase."""
        timer = patch("time.monotonic", return_value=1000.0)
        timer.start()
        self.addCleanup(timer.stop)
        self.f = ColdReadScopeFixture()
        self.addCleanup(self.f.cleanup)

    def _reject_replacement(self, path: Path) -> None:
        """Rewrite one allowlisted original file after the actual final claim document."""
        original = claim._document

        def document(ref: dict, maximum: int) -> tuple:
            """Actual parser first, then the exact named final-reader-return fault."""
            result = original(ref, maximum)
            if ref == self.f.inputs.value["documents"]["frameBindings"]:
                self.f.replace(path)
            return result

        with patch.object(claim, "_document", side_effect=document), \
                patch("guided_source_color_read.read_current_inputs", side_effect=AssertionError("late admission")):
            with self.assertRaisesRegex(RuntimeError, "entry file|ancestry"):
                read_source_color_result((self.f.inputs.path, self.f.output), self.f.authority, 300.0, self.f.transport)

    def test_actual_claim_final_document_cannot_rebaseline_original_claim(self) -> None:
        """Original RED accepted this changed mtime/ctime in the later scope constructor."""
        self._reject_replacement(self.f.held_claim.path)

    def test_actual_claim_final_document_cannot_rebaseline_original_input(self) -> None:
        """The input read at claim entry remains the exact original through admission."""
        self._reject_replacement(self.f.inputs.path)

    def test_claim_callback_cannot_rebaseline_already_read_media_result(self) -> None:
        """The first verified raw completion stays held during the next metadata phase."""
        self._reject_replacement(self.f.output / "media-result.json")

    def test_claim_callback_cannot_rebaseline_original_sidecar(self) -> None:
        """A not-yet-parsed independently supplied sidecar still has its original inode."""
        self._reject_replacement(self.f.transport.input_path)

    def test_claim_callback_cannot_rebaseline_original_archive(self) -> None:
        """The archived reservation is held without opening today's active marker."""
        self._reject_replacement(self.f.transport.archive_path)

    def test_claim_callback_cannot_rebaseline_fixed_evidence_sibling(self) -> None:
        """The expected new evidence path is held even before receipt projection uses it."""
        self._reject_replacement(self.f.output / "source-color-evidence.json")

    def test_copied_entry_fields_do_not_create_registered_initial_evidence(self) -> None:
        """Neither a DTO nor dataclass copy can become an original-entry capability."""
        with self.assertRaisesRegex(RuntimeError, "entry capture"):
            assert_source_color_read_entry(copy(self.f.entry), self.f.clock)

    def test_changed_early_authority_rejects_before_any_source_admission(self) -> None:
        """Permanent RED: changed SHA reached read_current_inputs before late refusal."""
        original = claim._document

        def document(ref: dict, maximum: int) -> tuple:
            """Mutate only this TEST authority after the original final claim document."""
            result = original(ref, maximum)
            if ref == self.f.inputs.value["documents"]["frameBindings"]:
                object.__setattr__(self.f.authority, "input_sha256", "9" * 64)
            return result

        with patch.object(claim, "_document", side_effect=document), \
                patch.object(reader, "read_current_inputs", return_value=self.f.inputs) as current:
            with self.assertRaisesRegex(RuntimeError, "original invocation"):
                read_source_color_result((self.f.inputs.path, self.f.output), self.f.authority, 300.0, self.f.transport)
        current.assert_not_called()

    def test_original_entry_cutoff_cannot_be_extended_before_scope_admission(self) -> None:
        """Permanent RED: entry and later actual scope silently adopted the longer end."""
        self.f.clock.end = 1600.0
        with self.assertRaises(RuntimeError):
            assert_source_color_read_entry(self.f.entry, self.f.clock)

    def test_equal_replacement_clock_is_not_the_original_entry_clock(self) -> None:
        """A newly constructed equal clock cannot acquire an existing entry's lifetime."""
        replacement = OpeningExecutionClock(self.f.clock.end)
        with self.assertRaises(RuntimeError):
            assert_source_color_read_entry(self.f.entry, replacement)


if __name__ == "__main__":
    unittest.main()

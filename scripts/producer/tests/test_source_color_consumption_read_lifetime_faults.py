"""Retained cold consumption fault checks; all files and native leaves are TEST-only.

Only exact allowlisted generated TEMP files may change. No production/source
inventory, native process, current tool bytes or observation owner is touched.
"""
from __future__ import annotations

from contextlib import ExitStack
import os
import unittest
from unittest.mock import patch

from _source_color_consumption_read_fixture import ConsumptionReadFixture
from audio import audio_mix_picture
from guided_source_color_consumption_files import ConsumptionReadFiles
from guided_source_color_consumption_read import hold_source_color_consumption


class ConsumptionLifetimeFaultTests(unittest.TestCase):
    """Returned holds must retain their own original inventories across later AV work."""

    def setUp(self) -> None:
        """Run actual packet/file parsers beneath one explicitly stubbed ffprobe leaf."""
        self.f = object.__new__(ConsumptionReadFixture)
        self.addCleanup(self.f.cleanup)
        self.f.__init__()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {"PATH": str(self.f.tools)}))
        self.native = stack.enter_context(patch.object(audio_mix_picture, "_run", side_effect=self.f.native))
        self.held = hold_source_color_consumption(self.f.evidence, self.f.context)
        self.assertEqual(self.native.call_count, 3)

    def test_later_callback_cannot_clear_files_then_change_original_picture(self) -> None:
        """Removing visible inventory rows cannot erase the original held file identities."""
        def mutate() -> None:
            """Write only the fixture's exact regular, owned, single-link picture path."""
            self.held.files.clear()
            self.f.change(self.f.paths["pictureMaster"], b"TEST hidden picture change")
        self.f.on_guard = mutate
        with self.assertRaisesRegex(RuntimeError, "original|changed|retained"):
            ConsumptionReadFiles.check(self.held)
        self.assertEqual(self.native.call_count, 3)

    def test_later_callback_cannot_clear_native_then_change_actual_observation(self) -> None:
        """The original actual PictureSource return stays held without another native read."""
        picture = self.held.native[0][0]
        def mutate() -> None:
            """Change only in-memory TEST observer metadata after its actual parser return."""
            self.held.native.clear()
            object.__setattr__(picture, "sha256", "0" * 64)
        self.f.on_guard = mutate
        with self.assertRaisesRegex(RuntimeError, "original|changed|retained"):
            ConsumptionReadFiles.check(self.held)
        self.assertEqual(self.native.call_count, 3)

    def test_later_callback_cannot_clear_loaded_then_upgrade_returned_record(self) -> None:
        """Clearing parsed-return holds cannot turn a retained false flag into approval."""
        def mutate() -> None:
            """Mutate only this detached TEST result, never any source/evidence file."""
            self.held.loaded.clear()
            self.held.record["colorQualified"] = True
        self.f.on_guard = mutate
        with self.assertRaisesRegex(RuntimeError, "original|changed|retained"):
            ConsumptionReadFiles.check(self.held)
        self.assertEqual(self.native.call_count, 3)

    def test_class_dispatched_final_check_cannot_be_shadowed_by_metadata_alias(self) -> None:
        """Outer class dispatch must not defer its retained-file checks to a replaced method."""
        self.held.metadata = lambda: None
        self.f.change(self.f.paths["pictureMaster"], b"TEST hidden behind method alias")
        with self.assertRaisesRegex(RuntimeError, "original|changed|retained"):
            ConsumptionReadFiles.assert_metadata(self.held)
        self.assertEqual(self.native.call_count, 3)


if __name__ == "__main__":
    unittest.main()

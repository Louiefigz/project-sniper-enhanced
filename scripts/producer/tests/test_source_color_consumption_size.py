"""Generated-media capture limits over tiny TEMP files and mocked stat sizes.

These tests exercise only the pre-payload role/capture boundary. No large file
is created, source opened or native observation run; reported sizes are TEST
metadata, not proof of media contents or a successful cold read.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from _source_color_consumption_read_fixture import ConsumptionReadFixture
from cut_preview_io import MAX_MEDIA
import guided_source_color_consumption_files as files
import guided_source_color_consumption_read as reader
import guided_source_color_observation_files as observation_files


class ConsumptionSizeTests(unittest.TestCase):
    """Retain existing payload ceilings without widening any source or metadata role."""

    def setUp(self) -> None:
        """Own only tiny fixture files; every later payload/native leaf must stay unused."""
        self.f = object.__new__(ConsumptionReadFixture)
        self.addCleanup(self.f.cleanup)
        self.f.__init__()
        self.full = deepcopy(self.f.evidence["fullProgram"])
        self.sizes: dict[Path, int] = {}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        original = observation_files._identity

        def identity(path: Path) -> tuple:
            """Keep real TEMP inode/ancestry fields, changing only explicitly selected size."""
            result = list(original(path))
            if path in self.sizes:
                result[6] = self.sizes[path]
            return tuple(result)

        self.stack.enter_context(patch.object(files, "_identity", side_effect=identity))
        self.stack.enter_context(patch.object(observation_files, "_identity", side_effect=identity))
        self.payload = [self.stack.enter_context(patch.object(module, name,
            side_effect=AssertionError("TEST capture must precede payload/native IO")))
            for module, name in ((files, "read_bytes"), (files, "file_hash"),
                                 (reader, "observe_picture_source"), (reader, "verify_picture_copy"))]
        self.held = files.ConsumptionReadFiles(self.f.evidence, self.f.context)

    def capture(self) -> dict:
        """Run actual original role selection and finite file capture, not later decoding."""
        return reader._references(self.held, self.f.consumed, self.full)

    def assert_no_payload(self) -> None:
        """Neither arbitrary admission callbacks nor payload/native work belongs to capture."""
        self.assertEqual(self.f.calls, 0)
        for leaf in self.payload:
            leaf.assert_not_called()

    def test_exact_existing_media_limit_is_accepted_for_both_roles(self) -> None:
        """Exactly 2GiB retains the existing cap; metadata/tool limits are unchanged."""
        self.assertEqual(MAX_MEDIA, 2 * 1024 ** 3)
        self.full["base"]["sizeBytes"] = MAX_MEDIA
        self.sizes = {self.f.paths[name]: MAX_MEDIA for name in ("base", "pictureMaster")}
        self.capture()
        for name in ("base", "pictureMaster"):
            self.assertEqual(self.held.files[str(self.f.paths[name])].maximum, MAX_MEDIA)
        self.assertEqual(self.held.files[str(self.f.paths["evidence"])].maximum, 16 * 1024 ** 2)
        self.assertEqual(self.held.files[str(self.f.paths["ffprobe"])].maximum, 512 * 1024 ** 2)
        self.assert_no_payload()

    def test_declared_base_limit_plus_one_refuses_before_payload(self) -> None:
        """A raw reference cannot promise a generated artifact above the existing limit."""
        self.full["base"]["sizeBytes"] = MAX_MEDIA + 1
        with self.assertRaisesRegex(RuntimeError, "size exceeds its role bound"):
            self.capture()
        self.assert_no_payload()

    def test_actual_base_limit_plus_one_refuses_before_payload(self) -> None:
        """A small declared size cannot hide a larger reported actual base inode."""
        self.sizes[self.f.paths["base"]] = MAX_MEDIA + 1
        with self.assertRaisesRegex(RuntimeError, "artifact exceeds its finite bound"):
            self.capture()
        self.assert_no_payload()

    def test_actual_picture_master_limit_plus_one_refuses_before_payload(self) -> None:
        """The derived picture-master ref lacks sizeBytes, so its actual stat must bound it."""
        self.sizes[self.f.paths["pictureMaster"]] = MAX_MEDIA + 1
        with self.assertRaisesRegex(RuntimeError, "artifact exceeds its finite bound"):
            self.capture()
        self.assert_no_payload()


if __name__ == "__main__":
    unittest.main()

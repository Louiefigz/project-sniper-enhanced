"""Pure TEST source command construction; never launch FFmpeg or admission."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import _guided_v6_short_source as fixture


class ExplicitSourceToolTests(unittest.TestCase):
    """The fixture obeys the existing absolute-executable process contract."""

    def test_missing_or_relative_tool_stops_before_signal_write(self) -> None:
        """Invalid controls must not even materialize the TEST audio bed."""
        for value in ("", "ffmpeg", "./ffmpeg"):
            with patch.dict(os.environ, {"HYPERFRAMES_FFMPEG_PATH": value}):
                self.assert_tool_blocks_before_io()

    def assert_tool_blocks_before_io(self) -> None:
        """No subprocess or fixture audio call is authorized on this path."""
        with patch.object(fixture, "write_calibration_bed") as audio, \
                patch.object(fixture, "run_text") as runner:
            with self.assertRaises(RuntimeError):
                fixture.synthesize(Path("/TEST-only-not-created"))
            audio.assert_not_called()
            runner.assert_not_called()

    def test_owned_request_uses_exact_canonical_explicit_tool(self) -> None:
        """Use an installed path as an inert token; execution is TEST-mocked."""
        executable = str(Path(sys.executable).resolve(strict=True))
        with tempfile.TemporaryDirectory(prefix="sniper-v6-source-command-") as raw:
            root = Path(raw).resolve()
            self.assert_request(root, executable)

    def assert_request(self, root: Path, executable: str) -> None:
        """Preserve no-overwrite and the bounded existing owned runner."""
        with patch.dict(os.environ, {"HYPERFRAMES_FFMPEG_PATH": executable}), \
                patch.object(fixture, "write_calibration_bed"), \
                patch.object(fixture, "run_text", return_value=CompletedProcess([], 0, "", "")) as runner:
            self.assertEqual(fixture.synthesize(root), root / "TEST-synthetic-source.mp4")
        request = runner.call_args.args[0]
        self.assertEqual(request.command[0], executable)
        self.assertIn("-n", request.command)
        self.assertEqual(request.cwd, str(root))
        self.assertEqual(request.timeout_seconds, 60)
        self.assertEqual(request.max_output_bytes, 1024 * 1024)


if __name__ == "__main__":
    unittest.main()

"""Compatibility checks for extracted picture arguments and caption-facing imports."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio import master, master_picture_options


class MasterPictureOptionsTests(unittest.TestCase):
    """Extraction must preserve exact picture timing, quoting and the existing command seam."""

    def test_existing_imports_still_resolve_to_the_shared_type_and_helpers(self) -> None:
        from audio.master import MasterSpec, _filter_quote, _subtitles_filter
        self.assertIs(MasterSpec, master_picture_options.MasterSpec)
        self.assertIs(_filter_quote, master_picture_options._filter_quote)
        self.assertIs(_subtitles_filter, master_picture_options._subtitles_filter)
        spec = MasterSpec("source", "output", fps=24, fps_exact="24000/1001", frame_count=25)
        self.assertEqual((spec.fps_exact, spec.frame_count, spec.picture_consumption), ("24000/1001", 25, None))

    def test_fractional_frame_rate_keeps_exact_existing_encoder_arguments(self) -> None:
        self.assertEqual(master._video_opts(24, "24000/1001"), [
            "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-b:v", "12M", "-maxrate", "12M", "-bufsize", "24M", "-g", "48",
            "-keyint_min", "48", "-sc_threshold", "0", "-flags", "+cgop", "-bf", "2",
            "-coder", "1", "-r", "24000/1001", "-fps_mode", "cfr", "-movflags", "+faststart"])

    def test_caption_paths_keep_quote_escaping_with_and_without_vendored_fonts(self) -> None:
        path = "/tmp/creator's captions.ass"
        escaped = "/tmp/creator'\\''s captions.ass"
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(master._subtitles_filter(path), f"subtitles=filename='{escaped}'")
        with tempfile.TemporaryDirectory(prefix="creator's-fonts-") as fonts:
            with patch.dict("os.environ", {"PRODUCER_FONTS_DIR": fonts}):
                expected = f"subtitles=filename='{escaped}':fontsdir='{master._filter_quote(fonts)}'"
                self.assertEqual(master._subtitles_filter(path), expected)

    def test_font_detection_preserves_vendored_precedence_and_injected_command(self) -> None:
        with tempfile.TemporaryDirectory() as fonts:
            (Path(fonts) / "Inter-Regular.ttf").touch()
            with patch.dict("os.environ", {"PRODUCER_FONTS_DIR": fonts}), \
                    patch.object(master, "_run", side_effect=AssertionError("should use vendored font")):
                self.assertTrue(master._inter_available())
        with patch.dict("os.environ", {}, clear=True):
            for listing, expected in (("Painter", False), ("Inter:style=Regular", True)):
                with patch.object(master, "_run", return_value=subprocess.CompletedProcess([], 0, listing)):
                    self.assertEqual(master._inter_available(), expected)
            with patch.object(master, "_run", side_effect=OSError("fc-list unavailable")):
                self.assertTrue(master._inter_available())


if __name__ == "__main__":
    unittest.main()

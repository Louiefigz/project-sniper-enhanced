"""Frame-exact current-token native regression; never real subtitle/creator approval."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import numpy as np

from _caption_karaoke_pixels import STYLES, colors, compilation, render, word_regions
from captions.caption_ass_projection import build_compiled_ass, build_local_cue_ass


class CaptionKaraokePixelTests(unittest.TestCase):
    """Use real font shaping and libass pixels, not presence of any yellow."""

    def _assert_frames(self, frames: np.ndarray, reference: np.ndarray,
                       context: tuple[dict, bool, int]) -> None:
        """Only current token fills change; every red-channel glyph position stays fixed."""
        cue, wrapped, offset = context
        regions = word_regions(reference, wrapped)
        mask = reference[:, :, 0] > 200
        for frame in range(cue["startFrame"], cue["endFrameExclusive"]):
            image = frames[frame - offset]
            for token, region in zip(cue["tokens"], regions):
                active = token["startFrame"] <= frame < token["endFrameExclusive"]
                actual = colors(image, region)
                self.assertGreater(actual["active" if active else "white"], 60,
                                   f"{token['text']} frame {frame}: {actual}")
                self.assertLess(actual["white" if active else "active"], 5,
                                f"{token['text']} frame {frame}: {actual}")
            self.assertTrue(np.array_equal(image[:, :, 0] > 200, mask),
                            f"glyph shaping/position changed at frame {frame}")

    def _run(self, rate: str, wrapped: bool) -> None:
        """Compare actual global/local output against an unchanged line-layout reference."""
        value = compilation(rate)
        styles = copy.deepcopy(STYLES)
        styles["karaoke"]["maxCharsPerLine"] = 4 if wrapped else 32
        line = copy.deepcopy(value)
        line["cues"][0]["mode"] = "line"
        before = copy.deepcopy(value)
        with tempfile.TemporaryDirectory(prefix="sniper-karaoke-pixels-", dir="/private/tmp") as directory:
            root = Path(directory)
            reference = render(root, build_compiled_ass(line, styles), rate)[48]
            actual = render(root, build_compiled_ass(value, styles), rate)
            local = render(root, build_local_cue_ass(value, value["cues"][0], styles), rate)
        self._assert_frames(actual, reference, (value["cues"][0], wrapped, 0))
        self._assert_frames(local, reference, (value["cues"][0], wrapped, 43))
        self.assertFalse((actual[42] > 0).any())
        self.assertFalse((actual[69] > 0).any())
        self.assertFalse((local[26] > 0).any())
        self.assertEqual(value, before, "the emitter must not change compiled timing/layout")

    def test_integer_unwrapped_every_token_frame_and_gap(self) -> None:
        """Integer cadence: first/last token frames, silence and local shard parity."""
        self._run("30/1", False)

    def test_ntsc_wrapped_every_token_frame_and_gap(self) -> None:
        """NTSC cadence: wrapped glyph positions must remain identical across events."""
        self._run("30000/1001", True)


if __name__ == "__main__":
    unittest.main()

"""Full-vs-range pre-encode pixel oracles using actual shared graph commands.

This complements independent visible-marker endpoints. Lossy full/prefix H264
encodes can have different quantization; this deliberately compares the actual
uncompressed compositor output instead of pretending those bytes are equal.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from graphics.composite_core import CompositeOptions, composite
from test_opening_compositor_media import _clip, _ffmpeg


def _pixels(base: Path, clips: list[dict], options: tuple[str, tuple | None]) -> list[str]:
    """Execute the production graph but observe raw pixel hashes before lossy codec."""
    commands = []
    rate, span = options
    composite(str(base), clips, "unused-test-output.mp4", CompositeOptions(eof_pass=True,
        frame_rate=rate, frame_range=span, video_only=True, command_runner=commands.append))
    original = commands[0]
    command = original[:original.index("-c:v")] + ["-c:v", "rawvideo", "-pix_fmt", "yuv420p", "-an"]
    if span is not None:
        command += ["-frames:v", str(span[1] - span[0])]
    command += ["-f", "framemd5", "-"]
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=15)
    return [line.split(",")[-1].strip() for line in result.stdout.splitlines() if line and not line.startswith("#")]


class OpeningCompositorOracleTests(unittest.TestCase):
    """Compare actual decoded moving textures, not uniform color-only assertions."""

    def test_absolute_range_matches_full_pixels_with_animation_and_later_collisions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sniper-opening-pixel-oracle-") as temporary:
            root = Path(temporary)
            for rate in ("24", "30000/1001", "24000/1001"):
                case = root / rate.replace("/", "-")
                case.mkdir()
                base, first, later = (case / name for name in ("base.mp4", "first.mov", "later.mov"))
                _ffmpeg(["-f", "lavfi", "-i", f"testsrc2=size=64x36:rate={rate}:duration=1", "-frames:v", "12",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)])
                for index, path in enumerate((first, later)):
                    _ffmpeg(["-f", "lavfi", "-i", f"testsrc=size=64x36:rate={rate}:duration=1,format=argb",
                        "-vf", f"hue=h={index * 120},format=argb,colorchannelmixer=aa=0.7", "-c:v", "qtrle", str(path)])
                clips = [_clip(later, (5, 10), rate), _clip(first, (2, 8), rate)]
                full = _pixels(base, clips, (rate, None))
                for span in ((0, 6), (3, 9), (7, 12)):
                    with self.subTest(rate=rate, span=span):
                        self.assertEqual(_pixels(base, clips, (rate, span)), full[span[0]:span[1]])


if __name__ == "__main__":
    unittest.main(verbosity=2)

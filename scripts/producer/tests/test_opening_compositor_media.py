"""Real decoded exact-frame/alpha markers for the private compositor opt-in."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from graphics.composite_core import CompositeOptions, composite


def _ffmpeg(arguments: list[str]) -> bytes:
    """Only tiny generated owned media; no providers or creator footage."""
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", *arguments],
                          capture_output=True, check=True, timeout=15).stdout


def _fixture(root: Path, rate: str) -> tuple[Path, Path, Path]:
    """Black base and long alpha markers isolate the declared gate endpoints."""
    base, red, green = (root / name for name in ("base.mp4", "red.mov", "green.mov"))
    _ffmpeg(["-f", "lavfi", "-i", f"color=c=black:s=64x36:r={rate}:d=1", "-frames:v", "12",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)])
    for path, color in ((red, "red"), (green, "lime")):
        _ffmpeg(["-f", "lavfi", "-i", f"color=c={color}@0.8:s=64x36:r={rate}:d=1,format=argb",
                 "-c:v", "qtrle", str(path)])
    return base, red, green


def _clip(path: Path, frames: tuple[int, int], rate: str) -> dict:
    """Supply both original legacy timing and independently exact frame bindings."""
    return {"path": str(path), "outStart": float(Fraction(frames[0], 1) / Fraction(rate)),
        "outEnd": float(Fraction(frames[1], 1) / Fraction(rate)), "anchor": "own-screen",
        "startFrame": frames[0], "endFrameExclusive": frames[1]}


def _colors(path: Path) -> list[str]:
    """Observe actual encoded RGB pixels; labels tolerate ordinary codec rounding."""
    raw = _ffmpeg(["-i", str(path), "-map", "0:v:0", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
    size, offset = 64 * 36 * 3, (18 * 64 + 32) * 3
    colors = []
    for start in range(0, len(raw), size):
        red, green, _blue = raw[start + offset:start + offset + 3]
        colors.append("green" if green > 100 else "red" if red > 100 else "black")
    return colors


class OpeningCompositorMediaTests(unittest.TestCase):
    """Frame presence and layer oracle, not creator-level visual approval."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-opening-compositor-", dir="/private/tmp"))
        print(f"Synthetic compositor evidence: {cls.root}", flush=True)

    def test_exact_half_open_gates_and_collision_order_at_fractional_rates(self) -> None:
        for rate in ("24", "30000/1001", "24000/1001"):
            root = self.root / rate.replace("/", "-")
            root.mkdir()
            base, red, green = _fixture(root, rate)
            clips = [_clip(red, (2, 6), rate), _clip(green, (4, 8), rate)]
            full, prefix = root / "full.mp4", root / "prefix.mp4"
            composite(str(base), clips, str(full), CompositeOptions(eof_pass=True, frame_rate=rate, video_only=True))
            composite(str(base), clips, str(prefix), CompositeOptions(eof_pass=True, frame_rate=rate,
                      frame_range=(0, 6), video_only=True))
            expected = ["black"] * 2 + ["red"] * 2 + ["green"] * 4 + ["black"] * 4
            with self.subTest(rate=rate):
                self.assertEqual(_colors(full), expected)
                self.assertEqual(_colors(prefix), expected[:6])

    def test_legacy_inclusive_gate_is_not_mislabelled_as_exact_frames(self) -> None:
        root = self.root / "legacy"
        root.mkdir()
        base, red, _green = _fixture(root, "24")
        output = root / "legacy.mp4"
        composite(str(base), [_clip(red, (2, 6), "24")], str(output), CompositeOptions(eof_pass=True))
        self.assertEqual(_colors(output)[6], "red", "the old inclusive endpoint is a known separate policy")

    def test_ordinary_context_matches_full_timing_without_restarting_animation(self) -> None:
        root = self.root / "ordinary-context"
        root.mkdir()
        base, red, green = _fixture(root, "24")
        animation = root / "animated.mov"
        _ffmpeg(["-i", str(red), "-i", str(green), "-filter_complex",
                 "[0:v]trim=end_frame=4,setpts=PTS-STARTPTS[r];"
                 "[1:v]trim=end_frame=20,setpts=PTS-STARTPTS[g];[r][g]concat=n=2:v=1:a=0[v]",
                 "-map", "[v]", "-c:v", "qtrle", str(animation)])
        clips = [_clip(animation, (2, 8), "24")]
        full, window = root / "full.mp4", root / "context.mp4"
        composite(str(base), clips, str(full), CompositeOptions(eof_pass=True))
        composite(str(base), clips, str(window), CompositeOptions(eof_pass=True, frame_rate="24",
                  frame_range=(3, 9), video_only=True, ordinary_timing=True))
        self.assertEqual(_colors(window), _colors(full)[3:9])
        # The ordinary seconds gate rounds 8/24 to .3333; frame 8 is outside it.
        self.assertEqual(_colors(window), ["red"] * 3 + ["green"] * 2 + ["black"])

    def test_reversed_candidate_order_still_uses_ordinary_start_sort_and_stable_ties(self) -> None:
        root = self.root / "order"
        root.mkdir()
        base, red, green = _fixture(root, "30000/1001")
        for name, clips, expected in (
            ("reversed", [_clip(green, (4, 8), "30000/1001"), _clip(red, (2, 6), "30000/1001")],
             ["red", "green", "green", "green", "green", "black"]),
            ("ties", [_clip(green, (2, 8), "30000/1001"), _clip(red, (2, 6), "30000/1001")],
             ["red", "red", "red", "green", "green", "black"])):
            output = root / f"{name}.mp4"
            composite(str(base), clips, str(output), CompositeOptions(eof_pass=True,
                frame_rate="30000/1001", frame_range=(3, 9), video_only=True))
            with self.subTest(case=name):
                self.assertEqual(_colors(output), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)

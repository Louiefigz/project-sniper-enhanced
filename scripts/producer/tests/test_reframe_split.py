"""reframe_split tests: even-snap/cell-height arithmetic + real ffmpeg geometry.

The lint accept/reject matrix lives in test_plan_lint.py (ReframeLintTests);
here we test the EXECUTOR: denormalization math and — with ffmpeg present —
that a split render actually puts the top crop's pixels in the top cell and
the bottom crop's in the bottom cell (green/blue synthetic source).
"""
import os
import subprocess
import tempfile
import unittest

from _common import *  # noqa: F401,F403
from cut_speed import probe_video, probe_video_frames

# The known normalized regions the GEOMETRY PROOF uses (webcam inset + doc).
GREEN_CROP = [0.05, 0.55, 0.18, 0.32]
BLUE_CROP = [0.30, 0.05, 0.65, 0.85]


class SplitMathTests(unittest.TestCase):
    """Pure arithmetic: cell heights + denorm/even-snap — no ffmpeg needed."""

    def test_cell_heights_frac_05(self) -> None:
        self.assertEqual(rsp.cell_heights(0.5), (960, 960))

    def test_cell_heights_frac_06(self) -> None:
        self.assertEqual(rsp.cell_heights(0.6), (1152, 768))

    def test_cell_heights_always_even_and_telescope(self) -> None:
        for frac in (0.3, 0.37, 0.55, 0.61, 0.7):
            top, bottom = rsp.cell_heights(frac)
            self.assertEqual(top + bottom, 1920, f"frac {frac}")
            self.assertEqual(top % 2, 0, f"frac {frac}")
            self.assertEqual(bottom % 2, 0, f"frac {frac}")

    def test_cell_heights_frac_out_of_range_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            rsp.cell_heights(0.25)
        with self.assertRaises(RuntimeError):
            rsp.cell_heights(0.75)

    def test_denorm_even_snap(self) -> None:
        # 0.18*1920 = 345.6 and 0.32*1080 = 345.6 must snap to 346 (even).
        self.assertEqual(rsp.denorm_crop(GREEN_CROP, 1920, 1080, "t"),
                         (96, 594, 346, 346))

    def test_denorm_exact_pixels(self) -> None:
        self.assertEqual(rsp.denorm_crop(BLUE_CROP, 1920, 1080, "t"),
                         (576, 54, 1248, 918))

    def test_denorm_full_frame(self) -> None:
        self.assertEqual(rsp.denorm_crop([0, 0, 1, 1], 1920, 1080, "t"),
                         (0, 0, 1920, 1080))

    def test_denorm_out_of_frame_raises(self) -> None:
        # x+w = 1.01 → 960 + even(979.2)=980 → 1940 > 1920: must fail loudly.
        with self.assertRaises(RuntimeError) as cm:
            rsp.denorm_crop([0.5, 0.5, 0.51, 0.5], 1920, 1080, "split.top")
        self.assertIn("split.top", str(cm.exception))
        self.assertIn("leaves the 1920x1080 source frame", str(cm.exception))

    def test_denorm_even_snap_overflow_raises(self) -> None:
        # Snapping rounds OUTWARD past the edge: 0.999*1080 = 1078.9 → 1078,
        # h 0.001 → even(1.08) = 2 → y+h = 1080 fits; but 0.9995 → 1079.5 →
        # 1080 + 2 = 1082 > 1080 must fail (no clamping).
        with self.assertRaises(RuntimeError):
            rsp.denorm_crop([0.0, 0.9995, 1.0, 0.001], 1920, 1080, "t")


@unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg not on PATH")
class SplitRenderTests(unittest.TestCase):
    """Real renders on a synthetic 1920x1080 source: white base, GREEN webcam
    inset at GREEN_CROP, BLUE doc at BLUE_CROP, silent stereo audio."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dir = tempfile.mkdtemp(prefix="producer-rsplit-test-")
        cls.src = os.path.join(cls.dir, "synth.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error",
             "-f", "lavfi", "-i", "color=c=white:s=1920x1080:d=2:r=24",
             "-f", "lavfi", "-i",
             "anullsrc=channel_layout=stereo:sample_rate=48000",
             "-vf", ("drawbox=x=96:y=594:w=346:h=346:color=green:t=fill,"
                     "drawbox=x=576:y=54:w=1248:h=918:color=blue:t=fill"),
             "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
             "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", cls.src],
            check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        for name in os.listdir(cls.dir):
            os.remove(os.path.join(cls.dir, name))
        os.rmdir(cls.dir)

    @staticmethod
    def _half_means(path: str, t: float) -> tuple[list[float], list[float]]:
        """Mean [R,G,B] of the top and bottom halves of the frame at ``t``
        (decoded downscaled to 108x192 → pure-stdlib byte scan stays fast)."""
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(t), "-i", path,
             "-frames:v", "1", "-vf", "scale=108:192", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "pipe:1"],
            capture_output=True, check=True).stdout
        w, h = 108, 192
        halves = []
        for r0, r1 in ((0, h // 2), (h // 2, h)):
            n = (r1 - r0) * w
            sums = [0, 0, 0]
            for i in range(r0 * w * 3, r1 * w * 3, 3):
                sums[0] += raw[i]
                sums[1] += raw[i + 1]
                sums[2] += raw[i + 2]
            halves.append([s / n for s in sums])
        return halves[0], halves[1]

    def test_apply_split_top_green_bottom_blue(self) -> None:
        out = os.path.join(self.dir, "split.mp4")
        spec = {"top": {"crop": GREEN_CROP, "frac": 0.5},
                "bottom": {"crop": BLUE_CROP}}
        result = rsp.apply_split(self.src, spec, out)
        self.assertEqual(result["cellHeights"], [960, 960])
        self.assertEqual(result["topRect"], [96, 594, 346, 346])
        self.assertEqual(result["bottomRect"], [576, 54, 1248, 918])
        # Output geometry: exactly the 9:16 canvas, frame count preserved.
        from motion.reframe import probe_dims
        self.assertEqual(probe_dims(out), (1080, 1920))
        self.assertEqual(probe_video_frames(out), probe_video_frames(self.src))
        top, bottom = self._half_means(out, 1.0)
        self.assertGreater(top[1], 100, f"top not green: {top}")   # G dominant
        self.assertLess(top[0], 80, f"top not green: {top}")
        self.assertLess(top[2], 80, f"top not green: {top}")
        self.assertGreater(bottom[2], 150, f"bottom not blue: {bottom}")
        self.assertLess(bottom[1], 80, f"bottom not blue: {bottom}")

    def test_apply_split_frac_06_cells(self) -> None:
        out = os.path.join(self.dir, "split06.mp4")
        spec = {"top": {"crop": GREEN_CROP, "frac": 0.6},
                "bottom": {"crop": BLUE_CROP}}
        result = rsp.apply_split(self.src, spec, out)
        self.assertEqual(result["cellHeights"], [1152, 768])
        # The green/blue boundary moves to y=1152: sample rows around it.
        top, bottom = self._half_means(out, 1.0)
        self.assertGreater(top[1], 100)      # top half (0..960) inside 1152 top cell
        self.assertGreater(bottom[2], 90)    # bottom half spans seam; blue leads
        self.assertGreater(bottom[2], bottom[0])

    def test_apply_fill_crop_all_blue(self) -> None:
        out = os.path.join(self.dir, "fill.mp4")
        result = rsp.apply_fill(self.src, BLUE_CROP, out)
        self.assertEqual(result["rect"], [576, 54, 1248, 918])
        from motion.reframe import probe_dims
        self.assertEqual(probe_dims(out), (1080, 1920))
        top, bottom = self._half_means(out, 1.0)
        for half, name in ((top, "top"), (bottom, "bottom")):
            self.assertGreater(half[2], 150, f"{name} not blue: {half}")
            self.assertLess(half[1], 80, f"{name} not blue: {half}")

    def test_apply_split_out_of_frame_crop_fails_loudly(self) -> None:
        out = os.path.join(self.dir, "bad.mp4")
        spec = {"top": {"crop": [0.5, 0.5, 0.51, 0.5], "frac": 0.5},
                "bottom": {"crop": BLUE_CROP}}
        with self.assertRaises(RuntimeError) as cm:
            rsp.apply_split(self.src, spec, out)
        self.assertIn("leaves the 1920x1080 source frame", str(cm.exception))

    def test_apply_dispatch_rejects_unknown_layout(self) -> None:
        with self.assertRaises(RuntimeError) as cm:
            rsp.apply(self.src, {"layout": "stack"}, "/dev/null")
        self.assertIn("stack", str(cm.exception))


@unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg not on PATH")
class RotatedSourceTests(unittest.TestCase):
    """Edge I9 for MANUAL crops: rotation side data swaps the display canvas.

    A rotated-portrait source (1920x1080 stored + rotation=90 side data =
    1080x1920 AS DISPLAYED) must denormalize crops against the DISPLAY dims —
    the operator drew the rect on the display frame, and ffmpeg's filterchain
    autorotates, so a raw-dims rect (1920 wide) would not even fit the
    1080-wide frames the crop filter receives.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.dir = tempfile.mkdtemp(prefix="producer-rsplit-rot-")
        land = os.path.join(cls.dir, "land.mp4")
        cls.src = os.path.join(cls.dir, "rotated.mp4")
        # Stored landscape: left half green, right half blue → each DISPLAY
        # half (after autorotation) is one uniform color.
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error",
             "-f", "lavfi", "-i", "color=c=white:s=1920x1080:d=1:r=24",
             "-f", "lavfi", "-i",
             "anullsrc=channel_layout=stereo:sample_rate=48000",
             "-vf", ("drawbox=x=0:y=0:w=960:h=1080:color=green:t=fill,"
                     "drawbox=x=960:y=0:w=960:h=1080:color=blue:t=fill"),
             "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
             "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", land],
            check=True)
        # Stream-copy with rotation side data (iPhone-style portrait tag).
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-display_rotation", "90",
             "-i", land, "-c", "copy", cls.src], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        for name in os.listdir(cls.dir):
            os.remove(os.path.join(cls.dir, name))
        os.rmdir(cls.dir)

    def test_fixture_carries_rotation_side_data(self) -> None:
        """ffprobe must report the rotation — the fixture is real, not a no-op."""
        stream = probe_video(self.src)
        rotations = [int(float(s.get("rotation", 0)))
                     for s in stream.get("side_data_list", [])]
        self.assertTrue(any(abs(r) % 180 == 90 for r in rotations),
                        f"no 90-degree rotation side data: {stream!r}")
        self.assertEqual((int(stream["width"]), int(stream["height"])),
                         (1920, 1080))  # raw stored dims stay landscape
        self.assertEqual(rsp.probe_display_dims(self.src), (1080, 1920))

    def test_fill_crop_denorms_against_display_dims(self) -> None:
        """[0,0,1,0.5] of a rotated-portrait source = the DISPLAY top half:
        must resolve against 1080x1920 (not 1920x1080) and render it."""
        out = os.path.join(self.dir, "fill_rot.mp4")
        result = rsp.apply_fill(self.src, [0.0, 0.0, 1.0, 0.5], out)
        self.assertEqual(result["srcDims"], [1080, 1920])
        self.assertEqual(result["rect"], [0, 0, 1080, 960])
        from motion.reframe import probe_dims
        self.assertEqual(probe_dims(out), (1080, 1920))
        # The display top half is ONE uniform color (green or blue depending
        # on rotation direction — never the raw-dims mix of both): the whole
        # output must be that single saturated color.
        top, bottom = SplitRenderTests._half_means(out, 0.5)
        for c, name in enumerate("RGB"):
            self.assertLess(abs(top[c] - bottom[c]), 12,
                            f"{name} differs between halves — crop not "
                            f"display-oriented: top={top} bottom={bottom}")
        self.assertLess(top[0], 80, f"not a saturated green/blue crop: {top}")

    def test_split_denorms_against_display_dims(self) -> None:
        """Split cells of a rotated source resolve on the 1080x1920 canvas."""
        out = os.path.join(self.dir, "split_rot.mp4")
        spec = {"top": {"crop": [0.0, 0.0, 1.0, 0.5], "frac": 0.5},
                "bottom": {"crop": [0.0, 0.5, 1.0, 0.5]}}
        result = rsp.apply_split(self.src, spec, out)
        self.assertEqual(result["srcDims"], [1080, 1920])
        self.assertEqual(result["topRect"], [0, 0, 1080, 960])
        self.assertEqual(result["bottomRect"], [0, 960, 1080, 960])
        top, bottom = SplitRenderTests._half_means(out, 0.5)
        # Display halves are green and blue (order depends on rotation
        # direction): the two cells must be DIFFERENT saturated colors.
        self.assertGreater(abs(top[1] - bottom[1]) + abs(top[2] - bottom[2]),
                           150, f"cells not distinct: top={top} bottom={bottom}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

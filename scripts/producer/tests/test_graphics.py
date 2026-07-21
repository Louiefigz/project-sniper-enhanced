"""graphics tests (split from selftest.py)."""
from __future__ import annotations

import unittest
from unittest import mock

from _common import *  # noqa: F401,F403


class EmptyTrackPlacementsTests(unittest.TestCase):
    """run_graphics_stage passthrough — an empty plan never strands stale placements.

    A seeded QC round copies the prior candidate's graphics_placements.json
    beside the output; a repair that emptied graphicsTrack takes the
    passthrough, which never rewrites the sidecar — the stage must delete the
    stale copy so the prior round's evidence can't be promoted as this round's.
    """

    def _run_stage(self, placements_out: str | None) -> tuple[dict, str]:
        job = gs.GraphicsJob(video_in="in.mp4", video_out="out.mp4",
                             track=[], placements_out=placements_out)
        out = io.StringIO()
        with mock.patch.object(gs, "_run"), contextlib.redirect_stdout(out):
            summary = gs.run_graphics_stage(job)
        return summary, out.getvalue()

    def test_empty_track_clears_stale_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stale = os.path.join(tmp, "graphics_placements.json")
            with open(stale, "w") as f:
                json.dump([{"kind": "stat-card", "outStart": 1.0}], f)
            summary, log = self._run_stage(stale)
            self.assertFalse(os.path.exists(stale),
                             "the stale placements sidecar must be removed")
            self.assertEqual(summary["graphics"], 0)
            self.assertIn('"placements_cleared"', log)

    def test_empty_track_without_sidecar_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "graphics_placements.json")
            summary, log = self._run_stage(missing)
            self.assertFalse(os.path.exists(missing))
            self.assertEqual(summary["graphics"], 0)
            self.assertNotIn("placements_cleared", log)

    def test_empty_track_without_placements_out(self) -> None:
        summary, log = self._run_stage(None)
        self.assertEqual(summary["graphics"], 0)
        self.assertNotIn("placements_cleared", log)


class PipTakeoverTests(unittest.TestCase):
    """Takeover geometry math — the pure core of pip_takeover (no ffmpeg)."""

    def test_crop_4x5_centered_on_landscape(self) -> None:
        # 1920x1080 -> largest 4:5 keeps full height (1080), width 864, centred.
        cw, ch, cx, cy = pipt.crop_4x5(1920, 1080, 0.5)
        self.assertEqual((cw, ch), (864, 1080))
        self.assertEqual((cx, cy), (528, 0))                # (1920-864)/2, full height

    def test_crop_4x5_face_offset_clamps_inside_frame(self) -> None:
        # A face at the far edge clamps the crop x inside [0, src_w - cw].
        _, _, cx_hi, _ = pipt.crop_4x5(1920, 1080, 0.95)
        _, _, cx_lo, _ = pipt.crop_4x5(1920, 1080, 0.0)
        self.assertEqual(cx_hi, 1920 - 864)                 # right-clamped
        self.assertEqual(cx_lo, 0)                          # left-clamped

    def test_validate_card_guards_reserved_region(self) -> None:
        pipt.validate_card(pipt.DEFAULT_CARD)               # inside -> no raise
        rx, ry, rw, rh = pipt.RESERVED
        with self.assertRaises(ValueError):                 # spills past right edge
            pipt.validate_card((rx, ry, rw + 4, rh))
        with self.assertRaises(ValueError):                 # starts left of region
            pipt.validate_card((rx - 40, ry, 600, 750))

    def test_progress_is_a_clamped_smoothstep_trapezoid(self) -> None:
        ramp, length = 0.4, 3.6
        self.assertAlmostEqual(pipt.progress(0.0, ramp, length), 0.0)   # seed
        self.assertAlmostEqual(pipt.progress(ramp, ramp, length), 1.0)  # settled by knee
        self.assertAlmostEqual(pipt.progress(2.0, ramp, length), 1.0)   # hold
        self.assertAlmostEqual(pipt.progress(length, ramp, length), 0.0)  # back to seed
        # smoothstep midpoint of the entrance ramp = 0.5, and monotonic rising.
        self.assertAlmostEqual(pipt.progress(ramp / 2, ramp, length), 0.5)
        self.assertLess(pipt.progress(0.1, ramp, length),
                        pipt.progress(0.3, ramp, length))

if __name__ == "__main__":
    unittest.main(verbosity=2)

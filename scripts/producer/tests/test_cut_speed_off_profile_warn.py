"""The off-profile (letterbox) warning reads DISPLAY dimensions, not raw pixels.

Phone portrait footage is stored as landscape pixels plus a rotation flag (edge I9:
3840x2160 + rotation -90). The render already builds its canvas from the displayed
size; the warning must agree, or every rotated clip is reported as letterboxed when
it is not.
"""
import sys, unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cut_speed
from cut_speed import Profile, Segment


class OffProfileWarn(unittest.TestCase):
    def setUp(self):
        self.emitted = []
        self._emit = cut_speed.emit
        cut_speed.emit = lambda **row: self.emitted.append(row)
        self.addCleanup(setattr, cut_speed, "emit", self._emit)
        self._probe = cut_speed.probe_video

    def _probe_as(self, stream):
        cut_speed.probe_video = lambda _path: stream
        self.addCleanup(setattr, cut_speed, "probe_video", self._probe)

    def _run(self):
        cut_speed._warn_off_profile(
            [Segment(index=0, source_id="raw-1", src_start=0.0, src_end=1.0,
                     speed=1.0, out_start=0.0, out_end=1.0)],
            {"raw-1": "/dev/null"},
            Profile(width=2160, height=3840, fps=Fraction(30, 1), pix_fmt="yuv420p10le"))
        return [row for row in self.emitted if row.get("reason") == "letterbox"]

    def test_rotated_portrait_footage_is_not_reported_as_letterboxed(self):
        self._probe_as({"width": 3840, "height": 2160,
                        "side_data_list": [{"rotation": -90}]})
        self.assertEqual(self._run(), [], "rotated portrait fills a portrait profile")

    def test_genuine_landscape_footage_still_warns(self):
        self._probe_as({"width": 3840, "height": 2160, "side_data_list": []})
        self.assertEqual(len(self._run()), 1, "landscape into a portrait profile is padded")


if __name__ == "__main__":
    unittest.main()

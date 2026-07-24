"""Per-seam manifestation fallback (split rationale: same-scene mining cuts)."""
import unittest

from _common import *  # noqa: F401,F403
from audit import audit_motion as am


class SeamTimeTests(unittest.TestCase):
    def test_seam_times_from_cut_track(self) -> None:
        plan = {"cutTrack": [
            {"start": 10.0, "end": 21.0, "speed": 1.1},
            {"start": 30.0, "end": 41.0, "speed": 1.1},
            {"start": 50.0, "end": 52.0, "speed": 1.0},
        ]}
        seams = am._plan_seam_times(plan)
        self.assertEqual(len(seams), 2)
        self.assertAlmostEqual(seams[0], 10.0, places=3)
        self.assertAlmostEqual(seams[1], 20.0, places=3)

    def test_single_segment_has_no_seams(self) -> None:
        self.assertEqual(am._plan_seam_times(
            {"cutTrack": [{"start": 0, "end": 5}]}), [])

    def test_malformed_track_fails_closed_to_empty(self) -> None:
        self.assertEqual(am._plan_seam_times(
            {"cutTrack": [{"start": "x", "end": 5}, {"start": 1, "end": 2}]}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

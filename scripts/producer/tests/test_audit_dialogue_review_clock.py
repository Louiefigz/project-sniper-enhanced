"""The dialogue check's review clock is the PLAN's; the file is its frame-quantised encode.

Sections come from timeline_map (planned out_start/out_end) and are measured against the
decoded audio, so the last section can end a few milliseconds past the file: 7 segments at
30fps left 19.080s of sections over 19.066s of audio and failed the whole render's QC.
Rounding is tolerated; a real overshoot still fails.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit.dialogue_consistency import CLOCK_ROUNDING_TOLERANCE_S, _sections  # noqa: E402


def _plan(end):
    return {"audioReviewSections": [{"start": 0.0, "end": 1.0, "label": "picture cut 0: raw-1"},
                                    {"start": 1.0, "end": end, "label": "picture cut 1: raw-1"}]}


class ReviewClock(unittest.TestCase):
    def test_encode_rounding_is_clamped_not_failed(self):
        sections = _sections(_plan(19.080), 19.066)
        self.assertAlmostEqual(sections[-1].end, 19.066, places=6)

    def test_an_overshoot_too_large_for_rounding_still_fails(self):
        with self.assertRaises(ValueError):
            _sections(_plan(19.066 + CLOCK_ROUNDING_TOLERANCE_S + 0.01), 19.066)

    def test_a_section_starting_past_the_audio_still_fails(self):
        plan = {"audioReviewSections": [{"start": 20.0, "end": 20.5, "label": "picture cut 9: raw-1"}]}
        with self.assertRaises(ValueError):
            _sections(plan, 19.066)

    def test_ordering_is_still_required(self):
        plan = {"audioReviewSections": [{"start": 1.0, "end": 2.0, "label": "b"},
                                        {"start": 0.5, "end": 1.5, "label": "a"}]}
        with self.assertRaises(ValueError):
            _sections(plan, 10.0)


if __name__ == "__main__":
    unittest.main()

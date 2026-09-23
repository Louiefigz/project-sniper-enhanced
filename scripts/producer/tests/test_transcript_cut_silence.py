"""Acoustic seam length must follow kept audio, not displaced ASR words."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transcript_cut_contract import _validate_cuts
from transcript_cut_evidence import SourceEvidence


def _source(quiet: tuple[tuple[float, float], ...], measured: bool = True) -> SourceEvidence:
    """Model speech with a deliberately displaced word in a measured quiet run."""
    words = [{"word": "previous", "start": 0.2, "end": 0.5},
             {"word": "displaced", "start": 2.0, "end": 2.9},
             {"word": "next", "start": 4.5, "end": 4.8}]
    levels = tuple(-70.0 if any(left <= index * .02 < right for left, right in quiet)
                   else -40.0 for index in range(300))
    return SourceEvidence("raw", 6.0, "source.json", words, quiet if measured else (),
                          -55.0 if measured else None, levels if measured else ())


def _cuts(ranges: list[tuple[float, float]], speed: float = 1) -> dict:
    """Provide source-ordered kept clips with meaningful author rationale."""
    return {"cutTrack": [{"sourceId": "raw", "start": start, "end": end,
                          "speed": speed, "rationale": "Keep this complete spoken thought."}
                         for start, end in ranges]}


def _check(plan: dict, source: SourceEvidence) -> tuple[list[dict], list[str]]:
    """Exercise production cut validation, including admission and joined seams."""
    errors: list[str] = []
    seams, _ranges = _validate_cuts(plan, {"raw": source}, errors)
    return seams, errors


class RetainedSilenceTests(unittest.TestCase):
    def test_displaced_word_does_not_invent_long_trailing_silence(self) -> None:
        seams, errors = _check(_cuts([(0, 2.4)]), _source(((2.1, 3.0),)))
        self.assertEqual(errors, [])
        self.assertTrue(seams[0]["end"]["admittedByMeasuredSilence"])
        self.assertEqual(seams[0]["end"]["retainedSilenceS"], .3)
        self.assertEqual(seams[0]["end"]["silenceEvidence"], "measured-audio")

    def test_displaced_word_does_not_invent_long_leading_silence(self) -> None:
        seams, errors = _check(_cuts([(2.7, 6)]), _source(((2.1, 3.0),)))
        self.assertEqual(errors, [])
        self.assertEqual(seams[0]["start"]["retainedSilenceS"], .3)

    def test_actual_long_retained_quiet_still_fails(self) -> None:
        _seams, errors = _check(_cuts([(0, 2.4)]), _source(((1.4, 3.0),)))
        self.assertTrue(any("1.000s measured retained silence" in error for error in errors), errors)

    def test_no_audio_preserves_conservative_transcript_rule(self) -> None:
        _seams, errors = _check(_cuts([(0, 3.9)]), _source((), measured=False))
        self.assertTrue(any("1.000s gap to its nearest kept word" in error for error in errors), errors)

    def test_audible_word_is_still_refused(self) -> None:
        _seams, errors = _check(_cuts([(0, 2.4)]), _source(((3.0, 4.0),)))
        self.assertTrue(any("cuts through word 'displaced'" in error for error in errors), errors)

    def test_removed_time_is_not_charged_to_a_short_quiet_clip(self) -> None:
        seams, errors = _check(_cuts([(2.3, 2.7)]), _source(((1.0, 4.0),)))
        self.assertEqual(errors, [])
        self.assertEqual(seams[0]["start"]["retainedSilenceS"], .4)
        self.assertEqual(seams[0]["end"]["retainedSilenceS"], .4)

    def test_adjacent_quiet_clips_cannot_hide_a_long_join(self) -> None:
        seams, errors = _check(_cuts([(0, 1.6), (2.3, 2.9)]), _source(((1.0, 4.0),)))
        self.assertEqual(seams[1]["joinedLeadingSilenceS"], 1.2)
        self.assertTrue(any("joined seam" in error and "1.200s" in error for error in errors), errors)

    def test_short_join_preserves_the_limit(self) -> None:
        _seams, errors = _check(_cuts([(0, 1.2), (3.6, 6)]), _source(((1.0, 4.0),)))
        self.assertEqual(errors, [])

    def test_nonquiet_clip_resets_accumulated_silence(self) -> None:
        _seams, errors = _check(_cuts([(0, 1.2), (3.6, 6)]), _source(((1.0, 4.0), (5.0, 6.0))))
        self.assertEqual(errors, [])

    def test_retained_silence_uses_output_speed(self) -> None:
        seams, errors = _check(_cuts([(0, 2.4)], speed=2), _source(((1.4, 3.0),)))
        self.assertEqual(errors, [])
        self.assertEqual(seams[0]["end"]["retainedSilenceS"], .5)

    def test_slowdown_does_not_hide_excess_silence(self) -> None:
        _seams, errors = _check(_cuts([(0, 2.4)], speed=.25), _source(((2.1, 3.0),)))
        self.assertTrue(any("1.200s measured retained silence" in error for error in errors), errors)

    def test_invalid_speed_fails_closed(self) -> None:
        _seams, errors = _check(_cuts([(0, 2.4)], speed=0), _source(((2.1, 3.0),)))
        self.assertTrue(any("speed must be finite and positive" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()

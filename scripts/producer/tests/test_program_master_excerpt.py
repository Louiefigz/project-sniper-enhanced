"""Pure absolute sample-clock and unchanged ordinary-wrapper regression cases."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from audio.program_audio_clock import float_audio_clock
from audio.program_master_excerpt import sample_range
from guided_opening_audio import OpeningAudioDeadline, _range


class ProgramMasterExcerptClockTests(unittest.TestCase):
    """These arithmetic checks supplement, not replace, decoded media proof."""

    def test_absolute_half_ties_do_not_round_local_duration(self) -> None:
        span = sample_range((1, 3), ("32000/1001", 128))
        self.assertEqual((span["startSample"], span["endSampleExclusive"], span["samples"]),
                         (1502, 4504, 3002))
        self.assertNotEqual(span["samples"], 3003)

    def test_absolute_ntsc_tail_uses_exact_program_endpoint(self) -> None:
        span = sample_range((100, 120), ("30000/1001", 120))
        self.assertEqual(span["endSampleExclusive"], 192192)
        self.assertEqual(span["startSample"], 160160)

    def test_invalid_or_empty_frames_fail_without_coercion(self) -> None:
        for pair in ((True, 3), (-1, 3), (3, 3), (3, 2), (0, 121), (0.0, 3), [0, 3]):
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                sample_range(pair, ("30000/1001", 120))

    def test_invalid_frame_rate_or_total_is_rejected(self) -> None:
        for clock in (("0", 120), ("-30", 120), ("1/0", 120), (30, 120), ("30000/1001", True)):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                sample_range((0, 1), clock)

    def test_server_range_rejects_extra_fields_and_boolean(self) -> None:
        for value in ({"startFrame": True, "endFrameExclusive": 3},
                      {"startFrame": 0, "endFrameExclusive": 3, "duration": 1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _range(value)

    def test_existing_ordinary_clock_wrapper_preserves_its_authority(self) -> None:
        bus = SimpleNamespace(samples=192192, admission=SimpleNamespace(tools={"ffprobe": {"path": "probe"}}))
        with patch("audio.program_audio_clock.exact_float_audio_clock", return_value={"samples": 192192}) as observe:
            self.assertEqual(float_audio_clock("full.wav", bus), {"samples": 192192})
        observe.assert_called_once_with("full.wav", "probe", 192192)

    def test_deadline_never_renews_remaining_time(self) -> None:
        deadline = OpeningAudioDeadline(100)
        with patch("guided_opening_audio.time.monotonic", side_effect=(40, 99, 101)):
            self.assertEqual(deadline.remaining(), 60)
            self.assertEqual(deadline.remaining(), 1)
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                deadline.remaining()


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Pure benchmark controls; no media, provider, process or fake performance numbers."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from _presenter_benchmark_io import BenchmarkClock
from benchmark_presenter_1080p import main, validate_output_streams


class PresenterBenchmarkControlTests(unittest.TestCase):
    """The engineering sample cannot acquire a renewed or configurable work budget."""

    def test_original_budget_includes_setup_and_clips_each_process(self) -> None:
        """Delayed setup and earlier work spend the same300s original allowance."""
        now = Mock(return_value=100)
        clock = BenchmarkClock(now)
        self.assertEqual(clock.process_seconds(), 60)
        now.return_value = 370
        self.assertEqual(clock.process_seconds(120), 30)
        self.assertEqual(clock.process_seconds(5), 5)
        now.return_value = 400
        with self.assertRaisesRegex(RuntimeError, "original300s"):
            clock.process_seconds()

    def test_invalid_or_override_arguments_never_begin_benchmark_work(self) -> None:
        """Only the exact explicit run flag may construct the actual process scope."""
        for arguments in ([], ["--run", "--seconds", "600"], ["--run", "--width", "64"]):
            with patch("benchmark_presenter_1080p.sys.argv", ["benchmark", *arguments]), \
                    patch("benchmark_presenter_1080p.run_benchmark") as run:
                self.assertEqual(main(), 2)
                run.assert_not_called()

    def test_complete_output_clock_and_no_audio_are_mandatory(self) -> None:
        """A shortened, downscaled, rate-shifted or audio-bearing encode fails the sample."""
        row = {"codec_type": "video", "width": 1920, "height": 1080, "pix_fmt": "yuv420p",
            "sample_aspect_ratio": "1:1", "nb_read_frames": "30", "start_pts": 0,
            "r_frame_rate": "30000/1001", "avg_frame_rate": "30000/1001"}
        self.assertEqual(validate_output_streams({"streams": [row]}), row)
        for changed in ({**row, "nb_read_frames": "29"}, {**row, "width": 64}, {**row, "avg_frame_rate": "30"}):
            with self.assertRaises(AssertionError):
                validate_output_streams({"streams": [changed]})
        with self.assertRaisesRegex(AssertionError, "no audio"):
            validate_output_streams({"streams": [row, {"codec_type": "audio"}]})


if __name__ == "__main__":
    unittest.main()

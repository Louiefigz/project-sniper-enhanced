"""Blocking boundaries, deadlines and truthful cleanup for native color probes."""
from __future__ import annotations

import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from color.deadline import wall_budget
from headless.color_diagnostic_native import analyze
from headless.color_diagnostic_policy import ColorIsolationError, run_isolated
from headless.native_media_runtime import NativeRuntimeError
from headless.process_runner import ProcessReapError

_REQUEST = {"sourceSha256": "a" * 64, "timeoutSeconds": 30, "samples": [{"id": "s", "sourceTime": 0.0}]}


class ColorDeadlineTests(unittest.TestCase):
    def test_actual_blocking_phase_is_interrupted_and_timer_restored(self) -> None:
        began = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "deadline"):
            with wall_budget(time.monotonic() + 0.03):
                time.sleep(2)
        self.assertLess(time.monotonic() - began, 0.5)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_actual_fifo_source_is_rejected_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fifo = Path(temporary).resolve() / "source.media"
            os.mkfifo(fifo)
            began = time.monotonic()
            result = analyze(str(fifo), dict(_REQUEST))
            self.assertEqual((result["status"], result["error"]), ("failed", "UNSAFE_SOURCE"))
            self.assertLess(time.monotonic() - began, 0.5)

    def test_expired_budget_reports_verified_cleanup_when_nothing_is_left(self) -> None:
        prefix = "headless.color_diagnostic_policy."
        with patch(prefix + "verified_runtime", side_effect=RuntimeError("deadline")):
            with self.assertRaisesRegex(ColorIsolationError, "deadline") as caught:
                run_isolated("/inert", dict(_REQUEST))
        self.assertTrue(caught.exception.cleanup_verified)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_unreaped_jailed_process_never_claims_cleanup(self) -> None:
        prefix = "headless.color_diagnostic_policy."
        with patch(prefix + "verified_runtime", return_value=object()), \
                patch(prefix + "analyze", side_effect=ProcessReapError("child process group remains after forced reap")):
            with self.assertRaises(ColorIsolationError) as caught:
                run_isolated("/inert", dict(_REQUEST))
        self.assertFalse(caught.exception.cleanup_verified)

    def test_missing_jail_fails_closed_without_host_fallback(self) -> None:
        with patch("headless.color_diagnostic_policy.verified_runtime",
                   side_effect=NativeRuntimeError("ffmpeg is not an executable")):
            with self.assertRaises(ColorIsolationError) as caught:
                run_isolated("/inert", dict(_REQUEST))
        self.assertTrue(caught.exception.cleanup_verified)
        self.assertIn("ffmpeg", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

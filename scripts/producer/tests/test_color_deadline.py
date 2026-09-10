"""Actual blocking boundaries and final work-budget rejection for color probes."""
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
from headless.color_diagnostic_policy import ColorIsolationError, _wait, run_isolated


class ColorDeadlineTests(unittest.TestCase):
    def test_actual_blocking_phase_is_interrupted_and_timer_restored(self) -> None:
        began = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "deadline"):
            with wall_budget(time.monotonic() + 0.03):
                time.sleep(2)
        self.assertLess(time.monotonic() - began, 0.5)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_actual_fifo_is_rejected_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "result").mkdir()
            os.mkfifo(root / "result/result.json")
            began = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, "regular"):
                _wait(str(root), time.monotonic() + 2)
            self.assertLess(time.monotonic() - began, 0.5)

    def test_expired_host_phase_still_removes_exact_owned_container(self) -> None:
        prefix = "headless.color_diagnostic_policy."
        with patch(prefix + "required_runtime", return_value=object()), \
                patch(prefix + "attest_image", return_value={"Id": "image"}), \
                patch(prefix + "container_command", return_value=("owned-name", [])), \
                patch(prefix + "_launch", return_value="owned-id"), \
                patch(prefix + "attest_probe_container", side_effect=RuntimeError("deadline")), \
                patch(prefix + "remove_container", return_value={"canonicalAbsenceProved": True}) as removal:
            with self.assertRaisesRegex(ColorIsolationError, "deadline") as caught:
                run_isolated("/inert", {"timeoutSeconds": 30})
            self.assertTrue(caught.exception.cleanup_verified)
            self.assertEqual(removal.call_args.args[2], "owned-id")
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_uncertain_removal_never_claims_cleanup(self) -> None:
        prefix = "headless.color_diagnostic_policy."
        for outcome in ({"canonicalAbsenceProved": False}, RuntimeError("removal timeout")):
            with patch(prefix + "required_runtime", return_value=object()), \
                    patch(prefix + "attest_image", return_value={"Id": "image"}), \
                    patch(prefix + "container_command", return_value=("owned-name", [])), \
                    patch(prefix + "_launch", return_value="owned-id"), \
                    patch(prefix + "attest_probe_container", side_effect=RuntimeError("worker failure")), \
                    patch(prefix + "remove_container") as removal:
                if isinstance(outcome, Exception):
                    removal.side_effect = outcome
                else:
                    removal.return_value = outcome
                with self.assertRaises(ColorIsolationError) as caught:
                    run_isolated("/inert", {"timeoutSeconds": 30})
                self.assertFalse(caught.exception.cleanup_verified)

    def test_proven_no_launch_can_release_even_on_configuration_failure(self) -> None:
        with patch("headless.color_diagnostic_policy.required_runtime", side_effect=RuntimeError("configuration")):
            with self.assertRaises(ColorIsolationError) as caught:
                run_isolated("/inert", {"timeoutSeconds": 30})
        self.assertTrue(caught.exception.cleanup_verified)


if __name__ == "__main__":
    unittest.main()

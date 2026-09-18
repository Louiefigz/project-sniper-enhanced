"""Virtual-time owned-result publication faults; no daemon or media activity."""
from __future__ import annotations

import subprocess
import unittest
from contextlib import ExitStack
from dataclasses import replace
from unittest import mock

from headless import owned_result_wait as wait
from test_external_media_probe import _runtime
from test_external_media_probe_wait import CONTAINER, EXITED, RUNNING

RAW = '{"status":"complete"}'


class OwnedResultWaitTests(unittest.TestCase):
    """Only bounded raw publication can succeed; terminal state is not removal."""

    def setUp(self) -> None:
        """Replace time, daemon observations and result reads with explicit fakes."""
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.now = 100.0
        self.context = wait.OwnedResultWait(_runtime(), "/TEST/private", CONTAINER, 1300.0)
        stack.enter_context(mock.patch.object(wait.time, "monotonic", side_effect=lambda: self.now))
        self.sleep = stack.enter_context(mock.patch.object(wait.time, "sleep", side_effect=self.advance))
        self.state = stack.enter_context(mock.patch.object(wait, "_state", return_value=RUNNING))
        self.read = mock.Mock(return_value=None)

    def advance(self, seconds: float) -> None:
        """Spend virtual elapsed time only; never sleep or start a child."""
        self.now += seconds

    def test_early_oom_does_not_spend_1200_seconds(self) -> None:
        """An exited OOM process fails after the terminal publication reread."""
        self.state.return_value = {**EXITED, "OOMKilled": True, "ExitCode": 137}
        with self.assertRaisesRegex(RuntimeError, "768 MiB.*OOMKilled"):
            wait.wait_owned_result(self.context, self.read)
        self.assertEqual(self.now, 100)
        self.assertEqual(self.read.call_count, 2)
        self.state.assert_called_once_with(_runtime(), "/TEST/private", CONTAINER, 15.0)
        self.sleep.assert_not_called()

    def test_exit_zero_is_not_success_or_cleanup(self) -> None:
        """Even normal exit without a publication is a failure, not approval."""
        for status in ("exited", "dead"):
            self.state.return_value = {**EXITED, "Status": status}
            with self.subTest(status=status), self.assertRaisesRegex(RuntimeError, "exit 0"):
                wait.wait_owned_result(self.context, self.read)

    def test_result_first_needs_no_daemon_observation(self) -> None:
        """The caller, not this raw waiter, must validate a published document."""
        self.read.return_value = RAW
        self.assertEqual(wait.wait_owned_result(self.context, self.read), RAW)
        self.state.assert_not_called()
        self.sleep.assert_not_called()

    def test_terminal_race_returns_exact_raw_failure_or_success(self) -> None:
        """Publication between first read and terminal inspect is not lost."""
        self.state.return_value = EXITED
        for raw in (RAW, '{"status":"failed","error":"TEST decode failure"}'):
            self.read.side_effect = [None, raw]
            with self.subTest(raw=raw):
                self.assertEqual(wait.wait_owned_result(self.context, self.read), raw)

    def test_running_exit_zero_has_bounded_inspection_frequency(self) -> None:
        """The daemon is polled no more often than every two seconds."""
        observed = []
        self.state.side_effect = lambda *_args: observed.append(self.now) or RUNNING
        self.read.side_effect = lambda: RAW if self.now >= 106 else None
        self.assertEqual(wait.wait_owned_result(self.context, self.read), RAW)
        self.assertGreater(len(observed), 1)
        self.assertTrue(all(b - a >= 2 for a, b in zip(observed, observed[1:])))
        self.assertGreater(self.read.call_count, self.state.call_count)

    def test_unknown_state_and_inspect_errors_are_not_proved_death(self) -> None:
        """Reuse the current strict state parser without normalizing uncertainty."""
        states = [None, {}, {**RUNNING, "Running": "false"},
                  {**RUNNING, "Status": "unknown"}, {**RUNNING, "Status": "exited"},
                  {**EXITED, "OOMKilled": "true"}, {**EXITED, "ExitCode": True}]
        for state in states:
            self.state.return_value = state
            with self.subTest(state=state), self.assertRaisesRegex(RuntimeError, "state.*(unavailable|malformed)"):
                wait.wait_owned_result(self.context, self.read)
        for error in (OSError("TEST daemon unavailable"), subprocess.TimeoutExpired(["TEST/docker"], 15)):
            self.state.side_effect = error
            with self.subTest(error=error), self.assertRaisesRegex(RuntimeError, "state observation failed"):
                wait.wait_owned_result(self.context, self.read)

    def test_final_inspection_receives_only_remaining_time(self) -> None:
        """A quarter-second remainder is not rounded up to another 15 seconds."""
        context = replace(self.context, deadline=100.25)
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            wait.wait_owned_result(context, self.read)
        self.state.assert_called_once_with(_runtime(), "/TEST/private", CONTAINER, 0.25)
        self.assertEqual(self.now, 100.25)

    def test_expiry_during_inspect_forbids_terminal_reread(self) -> None:
        """A terminal observation received after expiry cannot admit a late file."""
        self.state.side_effect = lambda *_args: self.advance(1) or EXITED
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            wait.wait_owned_result(replace(self.context, deadline=100.25), self.read)
        self.read.assert_called_once_with()

    def test_expiry_during_first_or_terminal_read_rejects_success(self) -> None:
        """Both result-first and publication-race reads remain in the same clock."""
        self.read.side_effect = lambda: self.advance(1201) or RAW
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            wait.wait_owned_result(self.context, self.read)
        self.now = 100
        self.read.reset_mock(side_effect=True)
        self.read.side_effect = lambda: None if self.read.call_count == 1 else self.advance(1200) or RAW
        self.state.return_value = EXITED
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            wait.wait_owned_result(self.context, self.read)

    def test_malformed_context_or_expired_clock_precedes_all_observations(self) -> None:
        """Private names, ambient mode, and renewed or nonfinite clocks are refused."""
        cases = [replace(self.context, container_id=value) for value in ("name", "A" * 64, "a" * 63, None)]
        cases += [replace(self.context, deadline=value) for value in (100, -1, True, float("nan"), float("inf"), 10 ** 400)]
        cases += [replace(self.context, config_dir="relative"), object()]
        for context in cases:
            with self.subTest(context=context), self.assertRaises(RuntimeError):
                wait.wait_owned_result(context, self.read)
        self.read.assert_not_called()
        self.state.assert_not_called()

    def test_invalid_reader_payload_is_not_implicitly_converted(self) -> None:
        """A reader cannot substitute parsed dictionaries or binary blobs."""
        for raw in ({"status": "complete"}, b"{}", False):
            self.read.return_value = raw
            with self.subTest(raw=raw), self.assertRaisesRegex(RuntimeError, "non-text"):
                wait.wait_owned_result(self.context, self.read)
        self.state.assert_not_called()


if __name__ == "__main__":
    unittest.main()

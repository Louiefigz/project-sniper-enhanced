"""Virtual-time probe polling and cleanup faults; never contact Docker or media."""
from __future__ import annotations

from contextlib import ExitStack
import json
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from headless import external_media_probe as probe
from headless.external_media_probe_policy import MediaProbeLimits
from test_external_media_probe import _runtime, _valid_document

CONTAINER = "a" * 64
RUNNING = {"Status": "running", "Running": True, "OOMKilled": False, "ExitCode": 0}
EXITED = {**RUNNING, "Status": "exited", "Running": False}
RAW = json.dumps(_valid_document())


class ProbeWaitTests(unittest.TestCase):
    """Local results remain authority; container states provide failure evidence only."""

    def setUp(self) -> None:
        """Stub every observation and advance a fake clock instead of sleeping."""
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.now = 100.0
        self.inspections: list[float] = []
        stack.enter_context(mock.patch.object(probe.time, "monotonic", side_effect=lambda: self.now))
        stack.enter_context(mock.patch.object(probe.time, "sleep", side_effect=self.advance))
        self.read = stack.enter_context(mock.patch.object(probe, "_read_result", return_value=None))
        self.state = stack.enter_context(mock.patch.object(probe, "_state", return_value=RUNNING))

    def advance(self, seconds: float) -> None:
        """Spend virtual time without starting background work."""
        self.now += seconds

    def test_early_oom_reports_specific_failure_without_full_wait(self) -> None:
        """A dead OOM container must not consume the 1220-second host ceiling."""
        self.state.return_value = {**EXITED, "OOMKilled": True, "ExitCode": 137}
        with self.assertRaisesRegex(RuntimeError, "768 MiB.*OOMKilled"):
            probe._wait_result(_runtime(), "/TEST/config", CONTAINER, 1220)
        self.assertEqual(self.now, 100)
        self.assertEqual(self.read.call_count, 2)
        self.state.assert_called_once_with(_runtime(), "/TEST/config", CONTAINER, 15.0)

    def test_zero_exit_without_result_is_failure_not_decode_success(self) -> None:
        """Container exit status cannot replace the validated result document."""
        for status in ("exited", "dead"):
            self.state.return_value = {**EXITED, "Status": status}
            with self.subTest(status=status), self.assertRaisesRegex(RuntimeError, "exit 0"):
                probe._wait_result(_runtime(), "/TEST/config", CONTAINER)

    def test_existing_result_needs_no_daemon_liveness_poll(self) -> None:
        """The worker may have already published and exited normally."""
        self.read.return_value = RAW
        self.assertEqual(probe._wait_result(_runtime(), "/TEST/config", CONTAINER), _valid_document())
        self.state.assert_not_called()

    def test_terminal_publication_race_rereads_and_keeps_rejection_validation(self) -> None:
        """A publish between the first read and inspect is consumed exactly once."""
        self.state.return_value = EXITED
        self.read.side_effect = [None, RAW]
        self.assertEqual(probe._wait_result(_runtime(), "/TEST/config", CONTAINER), _valid_document())
        self.read.side_effect = [None, '{"ok":false,"code":"TEST_DECODE_REJECTED"}']
        with self.assertRaisesRegex(RuntimeError, "TEST_DECODE_REJECTED"):
            probe._wait_result(_runtime(), "/TEST/config", CONTAINER)

    def test_running_exit_zero_waits_with_limited_inspection_frequency(self) -> None:
        """ExitCode zero on a running process is not terminal failure."""
        def observe(*_args: object) -> dict:
            """Retain actual fake-clock observation times for cadence assertions."""
            self.inspections.append(self.now)
            return RUNNING

        self.state.side_effect = observe
        self.read.side_effect = lambda *_args: RAW if self.now >= 106 else None
        self.assertEqual(probe._wait_result(_runtime(), "/TEST/config", CONTAINER), _valid_document())
        self.assertGreater(len(self.inspections), 1)
        self.assertTrue(all(b - a >= 2 for a, b in zip(self.inspections, self.inspections[1:])))
        self.assertGreater(self.read.call_count, self.state.call_count)

    def test_unknown_or_inconsistent_state_is_not_proved_death(self) -> None:
        """Missing/malformed daemon data rejects without inventing an exit cause."""
        cases = [None, {}, {**RUNNING, "Running": "false"},
                 {**RUNNING, "Status": "unknown"}, {**RUNNING, "Status": "exited"},
                 {**EXITED, "OOMKilled": "true"}, {**EXITED, "ExitCode": True}]
        for state in cases:
            self.state.return_value = state
            with self.subTest(state=state), self.assertRaisesRegex(RuntimeError, "state.*(unavailable|malformed)"):
                probe._wait_result(_runtime(), "/TEST/config", CONTAINER)

    def test_daemon_timeout_is_catchable_without_decode_or_false_cleanup(self) -> None:
        """A control-plane timeout reports unavailable observation, not success."""
        self.state.side_effect = subprocess.TimeoutExpired(["TEST/docker"], 15)
        with self.assertRaisesRegex(RuntimeError, "state observation failed"):
            probe._wait_result(_runtime(), "/TEST/config", CONTAINER)

    def test_inspection_uses_remaining_time_and_late_result_cannot_win(self) -> None:
        """The final daemon observation may not receive a fresh fifteen seconds."""
        probe._pending_result(_runtime(), "/TEST/config", CONTAINER, 100.25)
        self.state.assert_called_once_with(_runtime(), "/TEST/config", CONTAINER, 0.25)
        self.state.reset_mock()
        self.now = 101
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            probe._pending_result(_runtime(), "/TEST/config", CONTAINER, 100.25)
        self.state.assert_not_called()
        self.state.side_effect = lambda *_args: self.advance(1) or EXITED
        self.read.return_value = RAW
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            probe._pending_result(_runtime(), "/TEST/config", CONTAINER, 101.25)
        self.read.assert_not_called()

    def test_result_read_and_parse_remain_inside_original_deadline(self) -> None:
        """A successful late local read or parse cannot escape the work bound."""
        self.read.side_effect = lambda *_args: self.advance(111) or RAW
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            probe._wait_result(_runtime(), "/TEST/config", CONTAINER)
        self.read.side_effect = None
        self.read.return_value = RAW
        with mock.patch.object(probe, "_decode_result", side_effect=lambda _raw: self.advance(111) or {}), \
                self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            probe._wait_result(_runtime(), "/TEST/config", CONTAINER)

    def test_running_hang_spends_exact_original_wait_without_sleep_overshoot(self) -> None:
        """Known running state does not restart the aggregate host ceiling."""
        with self.assertRaisesRegex(RuntimeError, "exceeded 110"):
            probe._wait_result(_runtime(), "/TEST/config", CONTAINER)
        self.assertEqual(self.now, 210)


class ProbeStateAndCleanupTests(unittest.TestCase):
    """Exercise production inspect and finally seams with no real daemon calls."""

    def test_state_subprocess_timeout_is_bounded_and_validated_before_spawn(self) -> None:
        """The inspected ID and remaining timeout reach the existing CLI boundary."""
        result = subprocess.CompletedProcess([], 0, json.dumps(EXITED), "")
        with mock.patch.object(probe.subprocess, "run", return_value=result) as run:
            self.assertEqual(probe._state(_runtime(), "/TEST/config", CONTAINER, 0.25), EXITED)
            self.assertEqual(run.call_args.kwargs["timeout"], 0.25)
            self.assertIn(CONTAINER, run.call_args.args[0])
        for timeout in (0, -1, 16, True, float("nan")):
            with mock.patch.object(probe.subprocess, "run") as run, \
                    self.subTest(timeout=timeout), self.assertRaises(RuntimeError):
                probe._state(_runtime(), "/TEST/config", CONTAINER, timeout)
            run.assert_not_called()

    def _case(self, values: dict) -> tuple[dict | None, mock.Mock]:
        """Use actual _probe orchestration with exact fake execution observations."""
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            stack.enter_context(mock.patch.object(probe, "container_command", return_value=["TEST launch"]))
            stack.enter_context(mock.patch.object(probe, "_launch", return_value=CONTAINER))
            stack.enter_context(mock.patch.object(probe, "attest_probe_container", return_value={"containerId": CONTAINER}))
            stack.enter_context(mock.patch.object(probe, "probe_container", return_value={"TEST": True}))
            stack.enter_context(mock.patch.object(probe, "_read_result", side_effect=values["reads"]))
            state = stack.enter_context(mock.patch.object(probe, "_state",
                return_value=values.get("state", EXITED), side_effect=values.get("stateError")))
            remove = stack.enter_context(mock.patch.object(probe, "remove_container", return_value=values["removal"]))
            try:
                result = probe._probe(_runtime(), temporary, SimpleNamespace(path="/TEST/media"), MediaProbeLimits())
            finally:
                remove.assert_called_once_with(_runtime(), temporary, CONTAINER)
                self.assertEqual(state.call_args.args[2], CONTAINER)
        return result, remove

    def test_terminal_failure_still_removes_the_exact_launched_container(self) -> None:
        """Fast rejection goes through existing mandatory owner cleanup."""
        with self.assertRaisesRegex(RuntimeError, "exit 0"):
            self._case({"reads": [None, None], "removal": {"canonicalAbsenceProved": True}})

    def test_race_success_still_requires_document_validation_and_cleanup(self) -> None:
        """A race result traverses the real scalar admission validator."""
        result, _remove = self._case({"reads": [None, RAW], "removal": {"canonicalAbsenceProved": True}})
        self.assertTrue(result["decoded"]["decoded"])
        malformed = json.dumps({**_valid_document(), "extra": True})
        with self.assertRaisesRegex(RuntimeError, "malformed"):
            self._case({"reads": [None, malformed], "removal": {"canonicalAbsenceProved": True}})

    def test_unproved_cleanup_blocks_even_a_valid_terminal_race_result(self) -> None:
        """No early result or exit state substitutes for canonical absence proof."""
        with self.assertRaisesRegex(RuntimeError, "removal was not proved"):
            self._case({"reads": [None, RAW], "removal": {"canonicalAbsenceProved": False}})

    def test_unknown_state_and_daemon_timeout_still_use_exact_owner_cleanup(self) -> None:
        """Control uncertainty is failure, with cleanup still independently required."""
        for state in ({"state": None}, {"stateError": subprocess.TimeoutExpired(["TEST/docker"], 15)}):
            values = {"reads": [None], "removal": {"canonicalAbsenceProved": True}, **state}
            with self.subTest(state=state), self.assertRaisesRegex(RuntimeError, "state"):
                self._case(values)


if __name__ == "__main__":
    unittest.main()

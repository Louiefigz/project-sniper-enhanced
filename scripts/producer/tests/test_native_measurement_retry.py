"""Bound timeout recovery without fabricated telemetry, fresh budgets or launches."""
from __future__ import annotations

import base64
import io
import subprocess
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from native_render_processes import MissingProcessFootprint, ProcessIdentity
from native_render_resources import (
    GIB, ResourceCommandTimeout, ResourceMeasurementError, ResourcePolicy,
    _read_command, parse_snapshot, read_snapshot,
)
from studio.native_measurement_retry import MeasurementWindow, MeasurementWindowExpired
from studio.native_run import NativeRun
from test_native_render_resources import REQUEST, START, raw_sample, direct_sample


def timeout_error() -> ResourceCommandTimeout:
    """Represent an actual subprocess timeout with retained partial byte output."""
    command = ['/usr/bin/top', '-l', '1']
    return ResourceCommandTimeout(command, subprocess.TimeoutExpired(
        command, 3, output=b'partial\xff', stderr=b'diagnostic'))


def owner_fixture() -> SimpleNamespace:
    """Supply only the existing measurement owner's state and durable callbacks."""
    identity = ProcessIdentity(100, START, 100)
    registry = SimpleNamespace(known={100: identity}, live=Mock())
    return SimpleNamespace(project=Path('/private/tmp'), result={}, registry=registry,
                           started=time.monotonic(), deadline=60, abort_reason=None,
                           persist=Mock(), record_lease_processes=Mock())


class ResourceCommandTimeoutTests(unittest.TestCase):
    """Exercise real exception classification and read preservation without commands."""

    def test_timeout_retains_command_and_exact_partial_bytes(self) -> None:
        """Timeout is distinct from denied/malformed telemetry and keeps raw evidence."""
        command = ['/usr/bin/top', '-l', '1']
        error = subprocess.TimeoutExpired(command, 3, output=b'partial\xff', stderr=b'error')
        with patch('native_render_resources.subprocess.run', side_effect=error) as run:
            with self.assertLogs('native_render_resources', level='ERROR'):
                with self.assertRaises(ResourceCommandTimeout) as caught:
                    _read_command(command)
        evidence = caught.exception.evidence
        self.assertEqual(evidence['command'], command)
        self.assertEqual(evidence['timeoutSeconds'], 3)
        self.assertEqual(base64.b64decode(evidence['stdoutBase64']), b'partial\xff')
        self.assertEqual(base64.b64decode(evidence['stderrBase64']), b'error')
        self.assertEqual(run.call_args.kwargs['timeout'], 3)
        self.assertIs(caught.exception.__cause__, error)

    def test_timeout_preserves_completed_reads_and_discovered_child(self) -> None:
        """A child observed before a stalled sampler remains an ownership anchor on retry."""
        raw, error = raw_sample(), timeout_error()
        readings = [raw[key] for key in ('sysctl', 'pressure', 'ps')]
        with patch('native_render_resources._read_command', side_effect=readings + [error]):
            with self.assertRaises(ResourceCommandTimeout):
                read_snapshot(Path('/private/tmp'), REQUEST)
        self.assertEqual(error.evidence['completedReadings'],
                         {key: raw[key] for key in ('sysctl', 'pressure', 'ps')})
        self.assertIn(ProcessIdentity(101, START, 101), error.identities)

    def test_post_top_timeout_does_not_accept_unbracketed_memory(self) -> None:
        """Even a complete direct response needs the second process identity read."""
        raw, error = direct_sample(), timeout_error()
        readings = [raw[key] for key in ('sysctl', 'pressure', 'ps', 'direct')]
        with patch('native_render_resources._read_command', side_effect=readings + [error]):
            with self.assertRaises(ResourceCommandTimeout):
                read_snapshot(Path('/private/tmp'), REQUEST)
        self.assertEqual(error.evidence['completedReadings'], raw)


class MeasurementWindowTests(unittest.TestCase):
    """Keep the real retry window, inherited policy and shared ownership semantics."""

    def setUp(self) -> None:
        """Use synthetic complete host/process readings and no heavy work."""
        self.owner = owner_fixture()
        self.snapshot = parse_snapshot(raw_sample(), REQUEST, 40 * GIB)
        self.sleep = self.enterContext(patch('studio.native_measurement_retry.time.sleep'))

    def test_timeout_then_real_sample_keeps_evidence_and_rechecks_ownership(self) -> None:
        """Recovery returns the exact fresh snapshot, never the preceding partial data."""
        error = timeout_error()
        error.retain_readings({'ps': raw_sample()['ps']}, REQUEST)
        with patch('studio.native_measurement_retry.read_snapshot',
                   side_effect=[error, self.snapshot]) as read:
            result = MeasurementWindow(self.owner, REQUEST).run()
        self.assertIs(result, self.snapshot)
        self.assertIn(ProcessIdentity(101, START, 101), read.call_args.args[1].remembered)
        record = self.owner.result['measurementRetryWindows'][0]
        self.assertEqual([row['status'] for row in record['attempts']],
                         ['command-timeout', 'measured'])
        self.assertEqual(record['attempts'][0]['evidence'], error.evidence)
        self.assertEqual(self.owner.result['commandTimeoutMeasurementRetries'], 1)
        self.owner.registry.live.assert_called_once()
        self.owner.record_lease_processes.assert_called_once()

    def test_turnover_and_timeout_share_four_attempts(self) -> None:
        """Mixed failures cannot create nested retry budgets or erase prior evidence."""
        missing = MissingProcessFootprint((ProcessIdentity(102, START, 102),))
        with patch('studio.native_measurement_retry.read_snapshot',
                   side_effect=[missing, timeout_error(), timeout_error(), self.snapshot]) as read:
            self.assertIs(MeasurementWindow(self.owner, REQUEST).run(), self.snapshot)
        self.assertEqual(read.call_count, 4)
        self.assertEqual(self.owner.result['processExitMeasurementRetries'], 1)
        self.assertEqual(self.owner.result['commandTimeoutMeasurementRetries'], 2)
        self.assertEqual(len(self.owner.result['measurementFailureEvidence']), 3)
        self.assertIn(ProcessIdentity(102, START, 102), read.call_args.args[1].remembered)

    def test_exhausted_timeouts_fail_with_all_four_attempts(self) -> None:
        """A still-unmeasured tree stops at the existing limit and retains failures."""
        with patch('studio.native_measurement_retry.read_snapshot',
                   side_effect=[timeout_error() for _ in range(4)]) as read:
            with self.assertRaises(ResourceCommandTimeout):
                MeasurementWindow(self.owner, REQUEST).run()
        record = self.owner.result['measurementRetryWindows'][0]
        self.assertEqual(read.call_count, 4)
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(len(self.owner.result['measurementFailureEvidence']), 4)
        self.assertEqual(self.owner.result['commandTimeoutMeasurementRetries'], 3)
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [.1, .2, .4])
        self.assertEqual(record['maximumSamples'], 4)
        self.assertEqual(record['maximumWindowSeconds'], 18.0)

    def test_child_birth_burst_can_settle_without_exhausting_immediate_samples(self) -> None:
        """The faster sampler must not spend every retry inside one short child burst."""
        missing = MissingProcessFootprint((ProcessIdentity(102, START, 102),))
        with patch('studio.native_measurement_retry.time.monotonic', return_value=100) as now:
            self.owner.started = 100
            self.sleep.side_effect = lambda delay: setattr(now, 'return_value', now.return_value + delay)
            def burst_read(*_args: object) -> object:
                if now.return_value < 100.25:
                    raise missing
                return self.snapshot
            with patch('studio.native_measurement_retry.read_snapshot', side_effect=burst_read) as read:
                result = MeasurementWindow(self.owner, REQUEST).run()
        self.assertIs(result, self.snapshot)
        self.assertEqual(read.call_count, 3)
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [.1, .2])
        record = self.owner.result['measurementRetryWindows'][0]
        self.assertEqual(record['deadlineMonotonic'], 118)
        self.assertEqual(len(self.owner.result['measurementFailureEvidence']), 2)
        self.assertAlmostEqual(record['attempts'][0]['retryWaitElapsedSeconds'], .1)
        self.assertAlmostEqual(record['attempts'][1]['retryWaitElapsedSeconds'], .2)

    def test_original_deadline_expiring_during_backoff_prevents_another_read(self) -> None:
        """Scheduler delay cannot extend the original window or accept a late sample."""
        with patch('studio.native_measurement_retry.time.monotonic', return_value=100) as now:
            self.owner.started, self.owner.deadline = 100, .15
            self.sleep.side_effect = lambda _delay: setattr(now, 'return_value', 100.2)
            with patch('studio.native_measurement_retry.read_snapshot', side_effect=timeout_error()) as read:
                with self.assertRaises(MeasurementWindowExpired):
                    MeasurementWindow(self.owner, REQUEST).run()
        self.assertEqual(read.call_count, 1)
        self.sleep.assert_called_once_with(.1)
        self.assertEqual(self.owner.result['measurementRetryWindows'][0]['deadlineMonotonic'], 100.15)

    def test_cancellation_during_backoff_prevents_another_read(self) -> None:
        """An operator abort stays authoritative while waiting between real samples."""
        self.sleep.side_effect = lambda _delay: setattr(self.owner, 'abort_reason', 'operator canceled')
        with patch('studio.native_measurement_retry.read_snapshot', side_effect=timeout_error()) as read:
            with self.assertRaisesRegex(ResourceMeasurementError, 'operator canceled'):
                MeasurementWindow(self.owner, REQUEST).run()
        self.assertEqual(read.call_count, 1)

    def test_unrelated_errors_are_not_retried(self) -> None:
        """Denied, malformed, and failed commands still terminate immediately."""
        errors = (ResourceMeasurementError('malformed ps'), PermissionError('denied'),
                  subprocess.CalledProcessError(1, ['/usr/bin/top']))
        for error in errors:
            with self.subTest(error=error), patch('studio.native_measurement_retry.read_snapshot',
                                                side_effect=error) as read:
                with self.assertRaises(type(error)):
                    MeasurementWindow(owner_fixture(), REQUEST).run()
                self.assertEqual(read.call_count, 1)
        self.sleep.assert_not_called()

    def test_original_deadline_wins_over_fresh_window(self) -> None:
        """No new measurement budget extends an already exhausted owner deadline."""
        self.owner.started = time.monotonic() - 61
        with patch('studio.native_measurement_retry.read_snapshot') as read:
            with self.assertRaises(MeasurementWindowExpired):
                MeasurementWindow(self.owner, REQUEST).run()
        read.assert_not_called()

    def test_complete_but_late_sample_is_rejected(self) -> None:
        """Measured data arriving after the window cannot qualify continued work."""
        with patch('studio.native_measurement_retry.time.monotonic', return_value=100) as now:
            self.owner.started = 100
            def late_read(*_args: object) -> object:
                now.return_value = 119
                return self.snapshot
            with patch('studio.native_measurement_retry.read_snapshot', side_effect=late_read):
                with self.assertRaises(MeasurementWindowExpired):
                    MeasurementWindow(self.owner, REQUEST).run()
        self.assertEqual(self.owner.result['measurementRetryWindows'][0]['status'], 'failed')

    def test_cancellation_after_timeout_does_not_start_another_sample(self) -> None:
        """A requested abort remains authoritative while timeout evidence is recorded."""
        def canceled_read(*_args: object) -> None:
            self.owner.abort_reason = 'operator canceled'
            raise timeout_error()
        with patch('studio.native_measurement_retry.read_snapshot', side_effect=canceled_read) as read:
            with self.assertRaisesRegex(ResourceMeasurementError, 'operator canceled'):
                MeasurementWindow(self.owner, REQUEST).run()
        self.assertEqual(read.call_count, 1)
        self.assertEqual(len(self.owner.result['measurementFailureEvidence']), 1)

    def test_owner_pressure_checks_still_stop_after_timeout_recovery(self) -> None:
        """Run the inherited owner sample path; successful sampling is not healthy policy."""
        run = NativeRun.__new__(NativeRun)
        run.__dict__.update(vars(self.owner))
        run.child = Mock(pid=100)
        run.child.poll.return_value = None
        run.samples = io.StringIO()
        run.policy, run.baseline = ResourcePolicy(), self.snapshot
        run.registry.remember_measured = Mock()
        current = replace(self.snapshot, kernel_pressure_level=2)
        with patch('studio.native_measurement_retry.read_snapshot',
                   side_effect=[timeout_error(), current]), patch('builtins.print'):
            run.sample()
        self.assertEqual(run.abort_reason, 'kernel memory pressure is warning')
        self.assertIn('"kernel_pressure_level": 2', run.samples.getvalue())


if __name__ == '__main__':
    unittest.main()

"""Keep prelaunch retries owned, bounded and subject to the original admission caps."""
from __future__ import annotations

import base64
import json
import signal
import tempfile
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from native_render_processes import ProcessRequest, ResourceMeasurementError
from native_render_resources import GIB, admission_reasons, parse_snapshot
from studio.native_measurement_retry import MeasurementWindow
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, policy_for_baseline
from studio.native_runtime import digest
from test_native_measurement_retry import owner_fixture, timeout_error
from test_native_render_resources import REQUEST, START, raw_sample


class NativeBaselineAdmissionTests(unittest.TestCase):
    """Use real receipt files and owner lifecycle, with no browser, encoder or host lease."""

    def setUp(self) -> None:
        """Keep tests independent of the user's processes and signal handlers."""
        temporary = tempfile.TemporaryDirectory(prefix='native-baseline-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.project, self.output = root / 'project', root / 'output'
        self.project.mkdir(); self.output.mkdir()
        cli, sandbox = root / 'cli.js', root / 'sandbox.sb'
        cli.write_text('TEST executable fixture'); sandbox.write_text('TEST sandbox fixture')
        self.settings = NativeRunConfig(self.project, self.output, cli, ['TEST-NO-LAUNCH'], {},
            {'output': str(self.output / 'result.bin'), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
            sandbox=sandbox, success_status='TEST mocked lifecycle completed')
        self.run = NativeRun('baseline', self.settings)
        self.snapshot = parse_snapshot(raw_sample(), ProcessRequest(), 40 * GIB)
        self.lease = Mock()
        self.acquire = self.enterContext(patch('studio.native_run.NativeWorkLease.acquire', return_value=self.lease))
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            self.addCleanup(signal.signal, number, signal.getsignal(number))

    def execute(self, readings: object):
        """Exercise actual prepare/launch/cleanup/persist while replacing only external work."""
        child = Mock(pid=100, returncode=0)
        child.poll.return_value = 0
        registry = Mock(known={100: SimpleNamespace(pid=100, started=START, pgid=100)})
        registry.identities.return_value = [{'pid': 100, 'started': START, 'pgid': 100}]
        registry.cleanup.return_value = {'verified': True, 'TEST': 'mocked child absent'}
        def launched(*_args: object, **_kwargs: object):
            """Create a non-media output for the mocked child lifecycle."""
            Path(self.run.result['output']).write_bytes(b'TEST output; not a media qualification')
            return child
        with patch('studio.native_measurement_retry.read_snapshot', side_effect=readings) as read:
            with patch('studio.native_run.subprocess.Popen', side_effect=launched) as launch:
                with patch('studio.native_run.OwnedRegistry', return_value=registry), patch('builtins.print'):
                    success = self.run.execute()
        return success, read, launch

    def receipt(self) -> dict:
        """Reopen durable evidence instead of checking only the in-memory result."""
        return json.loads(self.run.path.read_text())

    def test_timeout_recovers_without_registry_and_keeps_original_start(self) -> None:
        """A complete fresh baseline is measured once and admitted before the one launch."""
        started, utc_started = self.run.started, self.run.result['startedAt']
        failure = timeout_error()
        failure.retain_readings({'ps': raw_sample()['ps']}, ProcessRequest())
        success, read, launch = self.execute([failure, self.snapshot])
        self.assertTrue(success); self.assertEqual(read.call_count, 2); launch.assert_called_once()
        self.assertTrue(all(call.args[1] == ProcessRequest() for call in read.call_args_list))
        self.assertIs(self.run.baseline, self.snapshot)
        receipt = self.receipt(); window = receipt['measurementRetryWindows'][0]
        self.assertEqual(window['phase'], 'baseline')
        self.assertEqual([row['status'] for row in window['attempts']], ['command-timeout', 'measured'])
        self.assertEqual(window['maximumSamples'], 4); self.assertEqual(window['maximumWindowSeconds'], 18)
        self.assertEqual(base64.b64decode(receipt['measurementFailureEvidence'][0]['stdoutBase64']), b'partial\xff')
        self.assertEqual(self.run.started, started); self.assertEqual(receipt['startedAt'], utc_started)
        self.assertTrue(receipt['cleanup']['verified']); self.lease.complete.assert_called_once()

    def test_four_baseline_timeouts_preserve_failure_without_any_launch(self) -> None:
        """The existing retry limit leaves a failed receipt and clears only the empty lease."""
        success, read, launch = self.execute([timeout_error() for _ in range(4)])
        self.assertFalse(success); self.assertEqual(read.call_count, 4); launch.assert_not_called()
        receipt = self.receipt(); window = receipt['measurementRetryWindows'][0]
        self.assertEqual(window['status'], 'failed'); self.assertEqual(len(window['attempts']), 4)
        self.assertTrue(all(row['status'] == 'command-timeout' for row in window['attempts']))
        self.assertNotIn('baseline', receipt); self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(receipt['cleanup'], {'verified': True, 'childNeverLaunched': True})
        self.lease.record_processes.assert_not_called(); self.lease.complete.assert_called_once()
        self.lease.close.assert_called_once()

    def test_prior_receipt_is_not_overwritten_or_reused(self) -> None:
        """Exclusive receipt ownership fails before telemetry, lease acquisition or launch."""
        original = b'TEST earlier receipt must remain byte-identical'
        self.run.path.write_bytes(original)
        success, read, launch = self.execute([self.snapshot])
        self.assertFalse(success); read.assert_not_called(); launch.assert_not_called()
        self.acquire.assert_not_called(); self.assertEqual(self.run.path.read_bytes(), original)
        self.assertTrue(self.run.result['receiptOwnershipFailed'])

    def test_recovered_warning_pressure_still_refuses_admission(self) -> None:
        """Retry success cannot turn a complete unhealthy baseline into healthy telemetry."""
        warning = replace(self.snapshot, kernel_pressure_level=2)
        success, read, launch = self.execute([timeout_error(), warning])
        self.assertFalse(success); self.assertEqual(read.call_count, 2); launch.assert_not_called()
        receipt = self.receipt()
        self.assertEqual(receipt['baseline']['kernel_pressure_level'], 2)
        self.assertIn('kernel memory pressure is warning', receipt['admissionReasons'])
        self.lease.complete.assert_called_once()

    def test_original_owner_deadline_prevents_first_baseline_read(self) -> None:
        """Creating the baseline window does not restart an exhausted run clock."""
        self.run.started = time.monotonic() - self.run.deadline - 1
        success, read, launch = self.execute([self.snapshot])
        self.assertFalse(success); read.assert_not_called(); launch.assert_not_called()
        self.assertIn('deadline already expired', self.receipt()['abortReason'])
        self.lease.complete.assert_called_once()

    def test_complete_but_late_baseline_cannot_launch(self) -> None:
        """The 18-second measurement bound rejects late complete data before admission."""
        with patch('studio.native_measurement_retry.time.monotonic', return_value=100) as now:
            self.run.started = 100
            def late_read(*_args: object):
                """Advance the measurement clock beyond the existing window."""
                now.return_value = 119
                return self.snapshot
            success, read, launch = self.execute(late_read)
        self.assertFalse(success); read.assert_called_once(); launch.assert_not_called()
        self.assertNotIn('baseline', self.receipt())
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0, 0))

    def test_cancellation_during_timeout_does_not_retry_or_launch(self) -> None:
        """Prelaunch abort requests follow the same evidence and no-child cleanup path."""
        def canceled_read(*_args: object):
            """Request owner cancellation during an actual retry boundary."""
            self.run.request_abort(signal.SIGTERM, None)
            raise timeout_error()
        success, read, launch = self.execute(canceled_read)
        self.assertFalse(success); read.assert_called_once(); launch.assert_not_called()
        receipt = self.receipt()
        self.assertIn('SIGTERM', receipt['abortReason']); self.assertTrue(receipt['measurementFailureEvidence'])
        self.lease.complete.assert_called_once()

    def test_unrelated_measurement_errors_are_not_retried(self) -> None:
        """A malformed measurement remains a terminal error with no partial fallback."""
        success, read, launch = self.execute([ResourceMeasurementError('TEST malformed telemetry')])
        self.assertFalse(success); read.assert_called_once(); launch.assert_not_called()
        self.assertIn('malformed telemetry', self.receipt()['abortReason'])
        self.lease.complete.assert_called_once()

    def test_deadline_after_preparation_still_prevents_launch(self) -> None:
        """Evidence-file work cannot authorize a launch after the original deadline."""
        with patch('studio.native_measurement_retry.read_snapshot', return_value=self.snapshot):
            self.run.prepare()
        self.run.started = time.monotonic() - self.run.deadline - 1
        with patch('studio.native_run.subprocess.Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, 'deadline exceeded before launch'):
                self.run.launch()
        launch.assert_not_called()
        self.run.cleanup(); self.run.release_lease()
        self.run.log.close(); self.run.samples.close()

    def test_fixed_and_short_policies_keep_existing_caps_and_formula(self) -> None:
        """Only the existing .25 floor / +1GiB / .4 cap compressor field may differ."""
        self.assertIs(policy_for_baseline(self.settings, self.snapshot), self.settings.policy)
        short = replace(self.settings, compressor_admission='short-headroom')
        for compressor in (2 * GIB, 23 * GIB, 30 * GIB):
            baseline = replace(self.snapshot, compressor_bytes=compressor)
            actual = policy_for_baseline(short, baseline)
            expected = replace(short.policy, maximum_compressor_fraction=min(.4, max(.25,
                (baseline.compressor_bytes + 1024 ** 3) / baseline.physical_bytes)))
            self.assertEqual(asdict(actual), asdict(expected))
        self.assertIn('physical memory occupied by the compressor exceeds policy', admission_reasons(baseline, actual))
        with self.assertRaisesRegex(ValueError, 'Unknown native compressor'):
            replace(self.settings, compressor_admission='unbounded')

    def test_baseline_policy_in_receipt_uses_the_recovered_snapshot(self) -> None:
        """The same complete baseline sets admission allowance and future swap-growth origin."""
        self.run = NativeRun('baseline', replace(self.settings, compressor_admission='short-headroom'))
        current = replace(self.snapshot, compressor_bytes=23 * GIB)
        success, read, _launch = self.execute([timeout_error(), current])
        self.assertTrue(success); self.assertEqual(read.call_count, 2)
        self.assertEqual(self.receipt()['policy']['maximum_compressor_fraction'], .375)
        self.assertEqual(self.receipt()['compressorAdmissionMode'], 'short-headroom')
        self.assertIs(self.run.baseline, current)

    def test_no_registry_cannot_measure_an_owned_request(self) -> None:
        """The new baseline mode does not authorize a live tree without its registry."""
        owner = owner_fixture(); owner.registry = None
        with patch('studio.native_measurement_retry.read_snapshot') as read:
            with self.assertRaisesRegex(ResourceMeasurementError, 'existing process registry'):
                MeasurementWindow(owner, REQUEST).run()
        read.assert_not_called()

    def test_owner_code_is_pinned_even_when_adapter_supplies_none(self) -> None:
        """Browser adapters cannot accidentally omit the shared memory/cleanup implementation."""
        self.assertFalse(self.settings.additional_pins)
        pinned = {Path(name).name for name in self.run.additional_pins}
        self.assertTrue({'native_run.py', 'native_render_resources.py', 'native_render_processes.py',
            'native_measurement_retry.py', 'native_owned_processes.py', 'native_work_lease.py'} <= pinned)
        success, _read, _launch = self.execute([self.snapshot])
        self.assertTrue(success)
        receipt = self.receipt()
        self.assertEqual(receipt['additionalFilePinsBefore'], receipt['additionalFilePinsAfter'])
        self.assertTrue(receipt['additionalFilesStable'])

    def test_stale_caller_code_pin_is_not_replaced_with_a_new_hash(self) -> None:
        """Automatic owner pinning cannot promote an obsolete prepared implementation."""
        filename = next(name for name in self.run.owner_pins if name.endswith('/native_run.py'))
        self.run = NativeRun('baseline', replace(self.settings, additional_pins={filename: '0' * 64}))
        success, read, launch = self.execute([self.snapshot])
        self.assertFalse(success); read.assert_not_called(); launch.assert_not_called()
        self.acquire.assert_not_called()
        self.assertEqual(self.receipt()['additionalFilePinsBefore'][filename], '0' * 64)
        self.assertIn('changed before launch', self.receipt()['abortReason'])

    def test_owner_code_change_during_admission_prevents_launch(self) -> None:
        """A fresh resource reading does not authorize changed supervision code."""
        changed = {**self.run.owner_pins, 'TEST new measurement implementation': '0' * 64}
        with patch('studio.native_run.owner_file_pins', return_value=changed):
            success, read, launch = self.execute([self.snapshot])
        self.assertFalse(success); read.assert_called_once(); launch.assert_not_called()
        self.assertIn('code changed during admission', self.receipt()['abortReason'])
        self.assertTrue(self.receipt()['cleanup']['verified'])

    def test_disappeared_pin_records_failure_without_masking_the_original_error(self) -> None:
        """An unreadable final pin cannot leave an owned receipt at preparing/running."""
        filename = self.output / 'TEST-dependency.py'
        filename.write_text('TEST temporary implementation')
        self.run = NativeRun('baseline', replace(self.settings,
            additional_pins={str(filename): digest(filename)}))
        filename.unlink()
        success, read, launch = self.execute([self.snapshot])
        self.assertFalse(success); read.assert_not_called(); launch.assert_not_called()
        receipt = self.receipt()
        self.assertEqual(receipt['status'], 'failed')
        self.assertIn('FileNotFoundError', receipt['abortReason'])
        self.assertEqual(receipt['pinVerificationError']['type'], 'FileNotFoundError')
        self.assertIsNone(receipt['additionalFilePinsAfter'])
        self.assertFalse(receipt['additionalFilesStable'])
        self.assertTrue(receipt['cleanup']['verified'])


if __name__ == '__main__':
    unittest.main()

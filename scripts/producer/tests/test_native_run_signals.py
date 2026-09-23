"""Return native signal ownership after every stage without launching real media work."""
from __future__ import annotations

import json
import signal
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from native_render_processes import ProcessRequest
from native_render_resources import GIB, parse_snapshot
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig
from studio.native_run_lifecycle import ABORT_SIGNALS
from studio.native_runtime import digest
from studio.native_short_pipeline import NativeShortPipeline
from test_native_render_resources import START, raw_sample


class NativeRunSignalTests(unittest.TestCase):
    """Exercise actual owner lifecycle and process signal APIs with mocked children."""

    def setUp(self) -> None:
        """Keep independent caller handlers and text-only process artifacts."""
        temporary = tempfile.TemporaryDirectory(prefix='native-signals-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project, self.output = self.root / 'project', self.root / 'output'
        self.project.mkdir()
        self.output.mkdir()
        runtime = self.root / 'runtime'
        (runtime / 'dist').mkdir(parents=True)
        cli, sandbox = runtime / 'dist/cli.js', self.root / 'sandbox.sb'
        cli.write_text('TEST executable fixture')
        sandbox.write_text('TEST sandbox fixture')
        self.settings = NativeRunConfig(self.project, self.output, cli, ['TEST-NO-LAUNCH'], {},
            {'output': str(self.output / 'result.bin'), 'sdkSha256': digest(cli),
             'sandboxSha256': digest(sandbox)}, sandbox=sandbox)
        self.request = {'project': str(self.project), 'output': str(self.output),
                        'runtime': str(runtime), 'pins': {}}
        (self.output / 'export-request.json').write_text(json.dumps(self.request))
        self.original_handlers = {number: signal.getsignal(number) for number in ABORT_SIGNALS}
        for number, handler in self.original_handlers.items():
            self.addCleanup(signal.signal, number, handler)
            signal.signal(number, self.caller_handler)
        self.lease = Mock()
        self.acquire = self.enterContext(patch('studio.native_run.NativeWorkLease.acquire', return_value=self.lease))
        snapshot = parse_snapshot(raw_sample(), ProcessRequest(), 40 * GIB)
        self.read = self.enterContext(patch('studio.native_measurement_retry.read_snapshot', return_value=snapshot))
        self.launch = self.enterContext(patch('studio.native_run.subprocess.Popen', side_effect=self.launched))
        registry = Mock(known={100: SimpleNamespace(pid=100, started=START, pgid=100)})
        registry.identities.return_value = [{'pid': 100, 'started': START, 'pgid': 100}]
        registry.cleanup.return_value = {'verified': True, 'TEST': 'mock child absent'}
        self.enterContext(patch('studio.native_run.OwnedRegistry', return_value=registry))
        self.enterContext(patch('builtins.print'))

    def caller_handler(self, _number: int, _frame: object) -> None:
        """Represent cancellation ownership held by a caller between native stages."""

    def replacement_handler(self, _number: int, _frame: object) -> None:
        """Represent a handler intentionally installed after native preparation."""

    def launched(self, *_args: object, **_kwargs: object) -> Mock:
        """Complete one fake child immediately; produce no actual media."""
        Path(self.settings.admission['output']).write_bytes(b'TEST output, not media')
        child = Mock(pid=100, returncode=0)
        child.poll.return_value = 0
        return child

    def assert_caller_owns_signals(self) -> None:
        """Check actual interpreter state, not only the helper's saved dictionary."""
        self.assertEqual({signal.getsignal(number) for number in ABORT_SIGNALS}, {self.caller_handler})

    def test_sequential_owners_restore_the_original_caller_handlers(self) -> None:
        """Every completed stage leaves the next stage the original caller's handlers."""
        for label in ('render', 'capture', 'verification'):
            run = NativeRun(label, self.settings)
            with self.subTest(label=label):
                self.assert_caller_owns_signals()
                self.assertTrue(run.execute())
                self.assert_caller_owns_signals()
                self.assertFalse(run.signal_handlers.previous)
        self.assertEqual(self.launch.call_count, 3)
        self.assertEqual(self.lease.complete.call_count, 3)

    def test_lease_acquisition_failure_restores_handlers(self) -> None:
        """A failure after signal registration must not retain an unstarted owner."""
        self.acquire.side_effect = RuntimeError('TEST lease refused')
        run = NativeRun('failed-setup', self.settings)
        self.assertFalse(run.execute())
        self.assert_caller_owns_signals()
        self.launch.assert_not_called()
        self.read.assert_not_called()

    def test_partial_signal_registration_failure_restores_successful_installs(self) -> None:
        """One failed registration must not leak handlers installed earlier in setup."""
        run = NativeRun('partial-signals', self.settings)
        original_signal = signal.signal
        def install(number: int, handler: object) -> object:
            """Fail only the second attempt-owned registration; allow restoration."""
            if number == signal.SIGTERM and handler == run.request_abort:
                raise ValueError('TEST signal registration failed')
            return original_signal(number, handler)
        with patch('studio.native_run_lifecycle.signal.signal', side_effect=install):
            self.assertFalse(run.execute())
        self.assert_caller_owns_signals()
        self.acquire.assert_not_called()
        self.launch.assert_not_called()

    def test_receipt_failure_before_install_does_not_change_handlers(self) -> None:
        """A refused reused attempt cannot take ownership of caller cancellation."""
        run = NativeRun('occupied', self.settings)
        run.path.write_text('TEST previous receipt')
        self.assertFalse(run.execute())
        self.assert_caller_owns_signals()
        self.assertEqual(run.path.read_text(), 'TEST previous receipt')
        self.acquire.assert_not_called()

    def test_unknown_external_handler_refuses_install_and_restores_earlier_handlers(self) -> None:
        """Python cannot restore an unrecognized C handler, so never replace one."""
        run = NativeRun('unknown-handler', self.settings)
        original_getsignal = signal.getsignal
        def current_handler(number: int) -> object:
            """Expose an unknown second handler without mutating real process state."""
            return None if number == signal.SIGTERM else original_getsignal(number)
        with patch('studio.native_run_lifecycle.signal.getsignal', side_effect=current_handler):
            self.assertFalse(run.execute())
        self.assert_caller_owns_signals()
        self.acquire.assert_not_called()
        self.launch.assert_not_called()
        self.assertIn('Cannot preserve the unknown SIGTERM handler', run.abort_reason)

    def test_finish_failure_restores_handlers_after_cleanup(self) -> None:
        """Final receipt errors still release temporary interpreter state."""
        run = NativeRun('finish-failure', self.settings)
        with patch.object(run, 'finish', side_effect=OSError('TEST final receipt unavailable')):
            with self.assertRaisesRegex(OSError, 'final receipt unavailable'):
                run.execute()
        self.assert_caller_owns_signals()
        self.lease.complete.assert_called_once()
        self.lease.close.assert_called_once()

    def test_cleanup_failure_restores_handlers_and_cannot_succeed(self) -> None:
        """Owned cleanup refusal remains terminal even though signal state is restored."""
        run = NativeRun('cleanup-failure', self.settings)
        with patch.object(run, 'cleanup', side_effect=RuntimeError('TEST cleanup unproved')):
            self.assertFalse(run.execute())
        self.assert_caller_owns_signals()
        self.assertFalse(run.result['cleanup']['verified'])
        self.lease.complete.assert_not_called()
        self.lease.close.assert_called_once()

    def test_external_replacement_is_not_overwritten_on_restore(self) -> None:
        """An external owner that replaces a handler retains that newer handler."""
        run = NativeRun('replaced-handler', self.settings)
        def monitor() -> None:
            """Install another owner's SIGTERM handler after the native launch."""
            signal.signal(signal.SIGTERM, self.replacement_handler)
        with patch.object(run, 'monitor', side_effect=monitor):
            self.assertTrue(run.execute())
        self.assertEqual(signal.getsignal(signal.SIGTERM), self.replacement_handler)
        self.assertEqual(signal.getsignal(signal.SIGINT), self.caller_handler)
        self.assertEqual(signal.getsignal(signal.SIGHUP), self.caller_handler)

    def test_handlers_remain_owned_through_finalization(self) -> None:
        """Cancellation during receipt closeout cannot grant permission for another phase."""
        run = NativeRun('late-cancel', self.settings)
        finish = run.finish
        def canceled_finish() -> None:
            """Deliver cancellation after durable closeout but before ownership returns."""
            finish()
            self.assertEqual(signal.getsignal(signal.SIGTERM), run.request_abort)
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        with patch.object(run, 'finish', side_effect=canceled_finish):
            self.assertFalse(run.execute())
        self.assertIn('SIGTERM', run.abort_reason)
        self.assert_caller_owns_signals()

    def test_pipeline_cancellation_cannot_launch_render_or_verification(self) -> None:
        """The coordinator stops when the early capture owner's baseline is canceled."""
        self.request.update(captureMode='sdk-streaming', tools={'node': '/TEST/node'})
        pipeline = NativeShortPipeline(self.request, {})
        snapshot = self.read.return_value
        def canceled_read(*_args: object) -> object:
            """Deliver the installed SIGTERM handler without signaling the test runner."""
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return snapshot
        self.read.side_effect = canceled_read
        with patch.object(pipeline, 'render') as render, patch.object(pipeline, 'verify') as verify:
            self.assertFalse(pipeline.execute())
        render.assert_not_called()
        verify.assert_not_called()
        self.launch.assert_not_called()
        self.assert_caller_owns_signals()
        self.assertEqual(json.loads((self.output / 'delivery.json').read_text())['status'], 'failed')
        self.assertIn('SIGTERM', json.loads((self.output / 'capture.render.json').read_text())['abortReason'])
        self.assertEqual(json.loads((self.output / 'delivery.json').read_text())['failureCategory'], 'cancelled')


if __name__ == '__main__':
    unittest.main()

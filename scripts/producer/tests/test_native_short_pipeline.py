"""Independent native phase orchestration tests with no render or provider calls."""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _native_short_pipeline_fixture import ShortPipelineFixture
from studio.native_runtime import digest
from studio.native_short_pipeline import FINAL_STATUS, RENDER_STATUS, NativeShortPipeline
from studio.native_short_resume import prepare_reverification
from studio.native_stage_evidence import read_stage
from studio.native_short_worker import execute as execute_worker


class NativeShortPipelineTests(unittest.TestCase):
    """Completed render bytes survive later phase failures and can be verified alone."""

    def setUp(self) -> None:
        """Exercise real filesystem receipts; only child execution is a TEST stub."""
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.fixture = ShortPipelineFixture(base)
        self.enterContext(mock.patch('studio.native_short_pipeline.NativeRun',
                                     side_effect=self.fixture.owner_factory))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def pipeline(self, request: dict | None = None) -> NativeShortPipeline:
        """Use the real coordinator with inert environment data."""
        return NativeShortPipeline(request or self.fixture.request, {'TEST_ONLY': '1'})

    def delivery(self, root: Path | None = None) -> dict:
        """Read the actual coordinator's persisted final status."""
        return json.loads(((root or self.fixture.root) / 'delivery.json').read_text())

    def test_default_runs_three_separate_owners_in_order(self) -> None:
        """No final success appears until render, capture and encoded QC complete."""
        self.assertTrue(self.pipeline().execute())
        calls = self.fixture.calls
        self.assertEqual([label for label, _ in calls], ['pipeline', 'capture', 'verification'])
        self.assertEqual([config.deadline for _, config in calls], [600, 600, 600])
        self.assertEqual(len({id(config) for _, config in calls}), 3)
        self.assertEqual(calls[0][1].command[-1], 'render')
        self.assertEqual(calls[2][1].command[-1], 'verify')
        self.assertEqual(self.delivery()['status'], FINAL_STATUS)
        self.assertFalse(self.delivery()['humanApproved'])
        for _, config in calls:
            self.assertIsNone(config.policy)
            self.assertEqual(config.compressor_admission, 'short-headroom')

    def test_streaming_capture_is_direct_node_under_owner_without_180s_helper(self) -> None:
        """Original single-session Node capture is unmodified and independently bounded."""
        with mock.patch('studio.native_short_delivery.run', side_effect=AssertionError('wrong runner')):
            self.assertTrue(self.pipeline().execute())
        config = self.fixture.calls[1][1]
        self.assertEqual(config.command[3], str(self.fixture.node))
        self.assertTrue(config.command[4].endswith('/native_short_capture.mjs'))
        self.assertEqual(config.command[5:], [str(self.fixture.root / 'export-request.json')])
        request = json.loads(Path(config.command[5]).read_text())
        self.assertEqual(request['captureMode'], 'sdk-streaming')
        self.assertGreater(config.deadline, 180)

    def test_batch_mode_preserves_existing_worker_capture_phase(self) -> None:
        """The new owner does not replace phased batch capture with streaming."""
        self.fixture.request['captureMode'] = 'cached-native-batches'
        self.fixture.write_request(self.fixture.request)
        self.assertTrue(self.pipeline().execute())
        config = self.fixture.calls[1][1]
        self.assertTrue(config.command[4].endswith('/native_short_worker.py'))
        self.assertEqual(config.command[-1], 'capture')
        self.assertEqual(self.delivery()['status'], FINAL_STATUS)

    def test_render_only_is_reusable_but_never_final_qualified(self) -> None:
        """Successful media generation cannot masquerade as a checked deliverable."""
        self.assertTrue(self.pipeline().execute(render_only=True))
        self.assertEqual([label for label, _ in self.fixture.calls], ['pipeline'])
        result = self.delivery()
        self.assertEqual(result['status'], RENDER_STATUS)
        self.assertNotIn('fullAudioVideoDecodePassed', result)
        self.assertFalse((self.fixture.root / 'checks.json').exists())
        record, _ = read_stage(Path(result['renderStage']), self.fixture.inputs, 'render')
        self.assertEqual(record['artifacts']['review']['sha256'], result['sha256'])

    def assert_capture_failure(self, failure: BaseException | bool) -> None:
        """A failed native capture leaves media reusable without starting decode."""
        self.fixture.failures['capture'] = failure
        self.assertFalse(self.pipeline().execute())
        self.assertEqual([label for label, _ in self.fixture.calls], ['pipeline', 'capture'])
        result = self.delivery()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue((self.fixture.root / 'render-stage.json').is_file())
        self.assertEqual(result['renderStage'], str(self.fixture.root / 'render-stage.json'))
        self.assertFalse((self.fixture.root / 'checks.json').exists())
        read_stage(Path(result['renderStage']), self.fixture.inputs, 'render')

    def test_capture_failure_preserves_completed_render_without_decode(self) -> None:
        """A failed owner cannot cause implicit picture/audio retry."""
        self.assert_capture_failure(False)

    def test_capture_timeout_preserves_completed_render_without_decode(self) -> None:
        """Owner timeout is terminal for this attempt, not a reason to rerender."""
        self.assert_capture_failure(subprocess.TimeoutExpired('TEST node capture', 600))
        self.assertEqual(self.delivery()['errorType'], 'TimeoutExpired')

    def test_capture_cancellation_preserves_completed_render_without_decode(self) -> None:
        """Cancellation still records the failed invocation and reusable stage path."""
        self.assert_capture_failure(KeyboardInterrupt('TEST cancellation'))
        self.assertEqual(self.delivery()['errorType'], 'KeyboardInterrupt')

    def test_child_zero_exit_with_failed_capture_receipt_cannot_run_decode(self) -> None:
        """A process success label cannot override failed actual capture checks."""
        self.fixture.capture_status = 'failed'
        self.assertFalse(self.pipeline().execute())
        self.assertEqual([label for label, _ in self.fixture.calls], ['pipeline', 'capture'])
        self.assertIn('reference checks', self.delivery()['error'])

    def test_resume_copies_exact_output_and_runs_only_capture_and_verification(self) -> None:
        """Verification is a new truthful receipt without picture/audio execution."""
        receipt = self.fixture.seal()
        original = {str(file): digest(file) for file in self.fixture.root.rglob('*') if file.is_file()}
        request = prepare_reverification(self.fixture.current(), receipt)
        output = Path(request['output'])
        output.mkdir()
        self.fixture.write_request(request)
        with mock.patch('studio.native_short_worker.render_media', side_effect=AssertionError('rendered')), \
                mock.patch('studio.native_short_worker.finish_dialogue', side_effect=AssertionError('encoded')):
            self.assertTrue(self.pipeline(request).execute())
        self.assertEqual([label for label, _ in self.fixture.calls], ['capture', 'verification'])
        self.assertEqual((output / 'review.mp4').read_bytes(), (self.fixture.root / 'review.mp4').read_bytes())
        self.assertFalse((output / 'picture.mp4').exists())
        self.assertFalse((output / 'audio').exists())
        self.assertTrue(self.delivery(output)['renderReused'])
        self.assertEqual(original, {name: digest(Path(name)) for name in original})

    def test_decode_failure_does_not_destroy_render_or_publish_success(self) -> None:
        """All capture work can finish while encoded QC rejects the deliverable."""
        self.fixture.failures['verification'] = False
        self.assertFalse(self.pipeline().execute())
        self.assertEqual(self.delivery()['status'], 'failed')
        self.assertTrue((self.fixture.root / 'native-frames.json').is_file())
        self.assertTrue((self.fixture.root / 'render-stage.json').is_file())

    def test_each_later_owner_binds_completed_media_and_earlier_evidence(self) -> None:
        """Phase separation cannot drop immutable output or preceding owner receipts."""
        self.assertTrue(self.pipeline().execute())
        capture, verify = self.fixture.calls[1][1], self.fixture.calls[2][1]
        root = self.fixture.root
        for config in (capture, verify):
            self.assertEqual(config.additional_pins[str(root / 'review.mp4')], digest(root / 'review.mp4'))
            self.assertIn(str(root / 'render-stage.json'), config.additional_pins)
            self.assertIn(str(root / 'pipeline.render.json'), config.additional_pins)
        self.assertIn(str(root / 'capture.render.json'), verify.additional_pins)
        self.assertIn(str(root / 'native-frames.json'), verify.additional_pins)

    def test_worker_verify_phase_never_enters_render_audio_or_capture(self) -> None:
        """The phase argument reaches shared encoded checks without earlier media work."""
        self.fixture.write_media(self.fixture.root)
        request_file = self.fixture.root / 'export-request.json'
        with mock.patch('studio.native_short_worker.render_media', side_effect=AssertionError('rerender')), \
                mock.patch('studio.native_short_worker.capture_checks', side_effect=AssertionError('recapture')), \
                mock.patch('studio.native_short_worker.qualify_picture', return_value={'comparisons': [1]}) as check:
            result = execute_worker(self.fixture.request, request_file, 'verify')
        check.assert_called_once_with(self.fixture.root, {'frameRate': '25/1', 'totalFrames': 25})
        self.assertEqual(result['status'], 'checks-passed-awaiting-owned-cleanup')
        self.assertTrue(result['fullAudioVideoDecodePassed'])

    def test_worker_capture_phase_calls_existing_checks_without_render_or_decode(self) -> None:
        """Batch owner dispatch still uses the shared phased-capture implementation."""
        request_file = self.fixture.root / 'export-request.json'
        with mock.patch('studio.native_short_worker.render_media', side_effect=AssertionError('rerender')), \
                mock.patch('studio.native_short_worker.verify_media', side_effect=AssertionError('decoded')), \
                mock.patch('studio.native_short_worker.capture_checks') as capture:
            result = execute_worker(self.fixture.request, request_file, 'capture')
        capture.assert_called_once_with(self.fixture.request, request_file)
        self.assertEqual(result['status'], 'native-references-and-seek-states-pass')

    def test_failed_render_never_creates_reusable_stage_or_later_owner(self) -> None:
        """Only successful supervised media work receives a render-stage seal."""
        self.fixture.failures['pipeline'] = False
        self.assertFalse(self.pipeline().execute())
        self.assertEqual([label for label, _ in self.fixture.calls], ['pipeline'])
        self.assertFalse((self.fixture.root / 'render-stage.json').exists())
        self.assertNotIn('renderStage', self.delivery())

    def test_verification_zero_exit_cannot_override_incomplete_decode_proof(self) -> None:
        """Final cleanup plus exit zero still requires the actual full-decode flag."""
        original = self.fixture.write_phase

        def missing_decode(label: str, root: Path) -> None:
            """Simulate an incomplete encoded checker output, not a media failure."""
            original(label, root)
            if label == 'verification':
                file = root / 'checks.json'
                checks = json.loads(file.read_text())
                checks.pop('fullAudioVideoDecodePassed')
                file.write_text(json.dumps(checks))

        with mock.patch.object(self.fixture, 'write_phase', side_effect=missing_decode):
            self.assertFalse(self.pipeline().execute())
        self.assertEqual(self.delivery()['status'], 'failed')
        self.assertIn('verification is incomplete', self.delivery()['error'])


if __name__ == '__main__':
    unittest.main()

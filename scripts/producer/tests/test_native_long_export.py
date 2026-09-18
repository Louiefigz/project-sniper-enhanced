"""Long-job clocks, early rejection, progress and pipeline-order regressions."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.native_long_contract import read_long_plan, sample_frame_count
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_workload import ProgressWatch, workload_budget
from studio.native_long_recovery import PICTURE_STATUS, prepare_picture_recovery
from studio.native_runtime import digest
from studio.native_long_worker import source_process_timeout_ms


class WorkloadTests(unittest.TestCase):
    """Fifteen-minute jobs must not inherit a Short's eight-minute child limit."""

    def test_long_deadline_exceeds_measured_capture_with_cleanup_margin(self) -> None:
        """Keep 30/60 fps and fractional rates explicit, with an independent idle cap."""
        for rate, frames in (('30/1', 27000), ('60/1', 54000), ('30000/1001', 26973)):
            budget = workload_budget({'frameRate': rate, 'totalFrames': frames})
            self.assertGreater(budget['pictureSeconds'], frames / 12.6926)
            self.assertGreater(budget['ownerSeconds'], budget['pictureSeconds'])
            self.assertLessEqual(budget['ownerSeconds'], 21600)
            self.assertEqual(budget['idleSeconds'], 600)

    def test_invalid_workloads_fail_before_launch(self) -> None:
        """Reject booleans, excess duration, zero rates and nonfinite clocks."""
        for rate, frames in (('30/1', True), ('30/1', 27001), ('0/1', 30), ('NaN', 30), ('120/1', 30)):
            with self.subTest(rate=rate, frames=frames), self.assertRaises((ValueError, ZeroDivisionError)):
                workload_budget({'frameRate': rate, 'totalFrames': frames})

    def test_inner_sdk_timeout_scales_with_its_parent_phase(self) -> None:
        """An enlarged outer deadline cannot conceal the SDK's old five-minute cap."""
        budget = workload_budget({'frameRate': '30/1', 'totalFrames': 27000})
        request = {'budget': budget}
        self.assertEqual(source_process_timeout_ms(request, 'picture'), 7350000)
        self.assertEqual(source_process_timeout_ms(request, 'capture'), 4245000)
        self.assertLess(source_process_timeout_ms(request, 'capture'), budget['sampleSeconds'] * 1000)

    def test_duplicate_logs_cannot_keep_stalled_capture_alive(self) -> None:
        """Count complete advancing records, including split writes, not log chatter."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'child.log'
            path.write_text('Streaming fra')
            watch = ProgressWatch(path, 0, 10)
            self.assertTrue(watch.inspect(1))
            with path.open('a') as handle:
                handle.write('me 1/100\n')
            self.assertTrue(watch.inspect(5))
            with path.open('a') as handle:
                handle.write('Streaming frame 1/100\nwarning still alive\n')
            self.assertFalse(watch.inspect(16))

    def test_progress_truncation_fails_closed(self) -> None:
        """A replaced/truncated progress stream cannot reset the owner's deadline."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'child.log'
            path.write_text('SNIPER_PROGRESS samples 1\n')
            watch = ProgressWatch(path, 0, 10)
            self.assertTrue(watch.inspect(1))
            path.write_text('')
            with self.assertRaisesRegex(RuntimeError, 'truncated'):
                watch.inspect(2)


class LongContractTests(unittest.TestCase):
    """Use real declared HTML and manifests; no fake claim of media execution."""

    def setUp(self) -> None:
        """Stage a minimal exact-clock source declaration."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.plan = {'schemaVersion': 1, 'canvas': {'width': 320, 'height': 180,
            'frameRate': '30/1', 'totalFrames': 120}, 'audio': {'file': 'assets/dialogue.wav'},
            'scenes': [{'startFrame': 0, 'endFrame': 60, 'mediaIds': ['first']},
                       {'startFrame': 60, 'endFrame': 120, 'mediaIds': ['second']}]}
        self.html = '''<div data-composition-id="test" data-width="320" data-height="180" data-duration="4">
          <video id="first" muted src="assets/picture.mp4" data-start="0" data-duration="2"></video>
          <video id="second" muted src="assets/picture.mp4" data-start="2" data-duration="2"></video>
          <audio id="voice" src="assets/dialogue.wav" data-start="0" data-duration="4"></audio></div>'''

    def read(self) -> dict:
        """Exercise the actual cold reader after each independent mutation."""
        (self.root / 'LONG-PROJECT.json').write_text(json.dumps(self.plan))
        (self.root / 'index.html').write_text(self.html)
        return read_long_plan(self.root)

    def test_exact_scene_inventory_and_sample_schedule(self) -> None:
        """Include the final frame and both sides of the internal scene change."""
        self.assertEqual(self.read()['canvas']['totalFrames'], 120)
        self.assertEqual(sample_frame_count(self.plan), 20)

    def test_scene_gap_duplicate_ids_and_missing_end_are_rejected(self) -> None:
        """Stop ambiguous plans before audio, probes or picture work."""
        for key, value in (('startFrame', 61), ('mediaIds', ['second', 'second']), ('endFrame', 119)):
            original = self.plan['scenes'][1][key]
            self.plan['scenes'][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.read()
            self.plan['scenes'][1][key] = original

    def test_audio_clock_and_late_media_mismatch_are_rejected(self) -> None:
        """Do not truncate dialogue to hide the final decoded-frame mismatch."""
        self.html = self.html.replace('data-duration="4"></audio>', 'data-duration="3.9"></audio>')
        with self.assertRaisesRegex(ValueError, 'complete program clock'):
            self.read()

    def test_an_entire_video_inside_a_scene_cannot_evade_endpoint_checks(self) -> None:
        """A brief unintended overlay between periodic samples is still rejected."""
        self.html = self.html.replace('</div>', '''<video id="hidden" muted src="assets/extra.mp4"
            data-start="0.5" data-duration="0.03333333333333333"></video></div>''')
        with self.assertRaisesRegex(ValueError, 'scene'):
            self.read()

    def test_premixed_program_rejects_unrepresented_html_audio_changes(self) -> None:
        """A WAV-only export must not silently discard visible editor gain policy."""
        original = self.html
        for attributes in ('data-volume="0.5"', 'muted'):
            self.html = original.replace('<audio ', f'<audio {attributes} ')
            with self.subTest(attributes=attributes), self.assertRaisesRegex(ValueError, 'premixed'):
                self.read()

    def test_seam_failure_prevents_full_picture(self) -> None:
        """The production pipeline must actually enforce the new pre-master gate."""
        pipeline = NativeShortPipeline({'adapter': 'native-long', 'output': str(self.root)}, {})
        with patch.object(pipeline, 'capture', side_effect=RuntimeError('stale layer')), \
                patch.object(pipeline, 'render') as render:
            self.assertFalse(pipeline.execute())
        render.assert_not_called()
        self.assertEqual(json.loads((self.root / 'delivery.json').read_text())['status'], 'failed')


class LongRecoveryMetadataTests(unittest.TestCase):
    """Exercise donor/changed-input decisions; shared seal validation is separately tested."""

    def setUp(self) -> None:
        """Retain real files while mocking only the separately qualified stage reader."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.attempt = self.root / 'attempt'; self.attempt.mkdir()
        source = self.root / 'source.wav'; source.write_bytes(b'TEST source, not real media')
        self.donor = self.root / 'donor'; self.donor.mkdir()
        for name in ('program-master.wav', 'candidate.mp4'):
            (self.donor / name).write_bytes(b'TEST donor, not real media')
        (self.donor / 'receipt.json').write_text('{}')
        self.original = {'adapter': 'native-long', 'project': str(self.root / 'project'),
            'runtime': 'TEST runtime', 'tools': {}, 'pins': {str(source): digest(source)},
            'audioDonor': str(self.donor / 'receipt.json'), 'preparedMaster': None}
        (self.attempt / 'export-request.json').write_text(json.dumps(self.original))
        self.preparation = self.attempt / 'audio-preparation'; self.preparation.mkdir()
        self.write_audio('audio-donor-checked-awaiting-picture')
        self.current = {**self.original, 'output': str(self.root / 'recovered'), 'audioDonor': None}
        self.seal = self.enterContext(patch('studio.native_long_recovery.read_stage', return_value=(
            {'successStatus': PICTURE_STATUS, 'artifacts': {'picture': {}}}, {})))

    def write_audio(self, status: str) -> None:
        """Provide only the preparation state needed for this decision-boundary test."""
        (self.preparation / 'receipt.json').write_text(json.dumps({'status': status,
            'donorReceipt': self.original['audioDonor'],
            'donorReceiptSha256': digest(self.donor / 'receipt.json'),
            'masterSha256': digest(self.donor / 'program-master.wav')}))

    def test_picture_recovery_preserves_the_original_aac_donor(self) -> None:
        """A checked donor preparation does not pretend to be a newly mastered WAV."""
        result = prepare_picture_recovery(self.current, self.attempt)
        self.assertEqual(result['audioDonor'], self.original['audioDonor'])
        self.assertIsNone(result['preparedMaster'])
        self.assertEqual(result['pins'][str(self.donor / 'candidate.mp4')], digest(self.donor / 'candidate.mp4'))

    def test_failed_audio_never_becomes_a_reusable_master(self) -> None:
        """Having a picture cannot authorize a failed early audio preparation."""
        self.write_audio('failed')
        with self.assertRaisesRegex(ValueError, 'checked audio'):
            prepare_picture_recovery(self.current, self.attempt)

    def test_changed_source_rejects_before_the_picture_seal_is_read(self) -> None:
        """A newer request cannot silently retain an earlier source or implementation."""
        self.current['pins'] = {key: '0' * 64 for key in self.original['pins']}
        with self.assertRaisesRegex(ValueError, 'input changed'):
            prepare_picture_recovery(self.current, self.attempt)
        self.seal.assert_not_called()


if __name__ == '__main__':
    unittest.main()

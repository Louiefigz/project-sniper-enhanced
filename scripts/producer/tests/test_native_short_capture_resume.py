"""Automatic checkpoint recovery contracts using only tiny TEST artifacts."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _native_short_pipeline_fixture import ShortPipelineFixture, write_json
from studio.native_runtime import digest
from studio.native_short_capture_resume import read_capture
from studio.native_short_export import main, prepare
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_short_resume import prepare_reverification, render_stage_for_attempt


class AutomaticCaptureResumeTests(unittest.TestCase):
    """Recovery retains original sources, owner cleanup, every JPEG and normal final QC."""

    def setUp(self) -> None:
        """Keep all effects in a new fixture; no native child is launched."""
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.f = ShortPipelineFixture(base)
        self.enterContext(mock.patch('studio.native_short_pipeline.NativeRun', side_effect=self.f.owner_factory))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def execute(self, request: dict, fail: str | None = None) -> bool:
        """Execute the real coordinator against the TEST owner factory."""
        root = Path(request['output'])
        root.mkdir(exist_ok=True)
        self.f.write_request(request)
        self.f.failures = {fail: False} if fail else {}
        self.f.calls.clear()
        return NativeShortPipeline(request, {}).execute()

    def capture(self) -> Path:
        """Complete capture while the final TEST verifier rejects the attempt."""
        self.assertFalse(self.execute(self.f.request, 'verification'))
        return self.f.root / 'render-stage.json'

    def test_successful_capture_is_sealed_before_failed_final_verification(self) -> None:
        """Capture success remains independently reusable when a later owner fails."""
        render = self.capture()
        record, pins = read_capture(self.f.root / 'capture-stage.json', render)
        self.assertEqual(record['successStatus'], 'native-reference-capture-complete')
        self.assertEqual(len(record['artifacts']), 4)
        verify = self.f.calls[-1][1]
        self.assertTrue(all(verify.additional_pins.get(file) == sha for file, sha in pins.items()))
        self.assertEqual(json.loads((self.f.root / 'delivery.json').read_text())['status'], 'failed')

    def test_standard_verify_from_runs_final_qc_only_after_capture_success(self) -> None:
        """Ordinary resume now copies exact media/native JSON without another capture."""
        render = self.capture()
        before = {file: digest(file) for file in self.f.root.rglob('*') if file.is_file()}
        request = prepare_reverification(self.f.current(), render)
        self.assertEqual(request['captureStage'], str(self.f.root / 'capture-stage.json'))
        self.assertTrue(self.execute(request))
        self.assertEqual([name for name, _ in self.f.calls], ['verification'])
        output = Path(request['output'])
        for name in ('review.mp4', 'native-frames.json'):
            self.assertEqual((output / name).read_bytes(), (self.f.root / name).read_bytes())
        self.assertEqual(before, {file: digest(file) for file in before})
        result = json.loads((output / 'delivery.json').read_text())
        self.assertEqual(result['stages'][0]['phase'], 'capture-reused')
        self.assertEqual(result['stages'][0]['additionalCaptureFrames'], 0)

    def test_failed_capture_recaptures_without_rerendering(self) -> None:
        """A missing completed capture requires its original full capture route."""
        self.assertFalse(self.execute(self.f.request, 'capture'))
        self.assertFalse((self.f.root / 'capture-stage.json').exists())
        request = prepare_reverification(self.f.current(), self.f.root / 'render-stage.json')
        self.assertNotIn('captureStage', request)
        self.assertTrue(self.execute(request))
        self.assertEqual([name for name, _ in self.f.calls], ['capture', 'verification'])

    def test_resume_from_later_attempt_and_repeated_recovery_preserve_capture(self) -> None:
        """Explicit attempts locate later capture without searching or rewriting history."""
        self.assertFalse(self.execute(self.f.request, 'capture'))
        render = self.f.root / 'render-stage.json'
        second = prepare_reverification(self.f.current(), render)
        self.assertFalse(self.execute(second, 'verification'))
        second_root = Path(second['output'])
        self.assertEqual(render_stage_for_attempt(second_root), render)
        third = prepare_reverification(self.f.current(self.f.base / 'third'), render, second_root)
        self.assertEqual(third['captureStage'], str(second_root / 'capture-stage.json'))
        self.assertFalse(self.execute(third, 'verification'))
        fourth = prepare_reverification(self.f.current(self.f.base / 'fourth'), render, Path(third['output']))
        self.assertTrue(self.execute(fourth))
        self.assertEqual([name for name, _ in self.f.calls], ['verification'])
        self.assertEqual(fourth['captureStage'], third['captureStage'])

    def test_legacy_successful_unsealed_capture_requires_full_owner_admission(self) -> None:
        """A crash before sealing can preserve work, but no receipt is relabeled."""
        render = self.capture()
        seal = self.f.root / 'capture-stage.json'
        seal.unlink()
        before = (self.f.root / 'capture.render.json').read_bytes()
        request = prepare_reverification(self.f.current(), render)
        self.assertTrue(seal.exists())
        self.assertEqual(request['captureStage'], str(seal))
        self.assertEqual(before, (self.f.root / 'capture.render.json').read_bytes())

    def test_corrupt_existing_seal_never_falls_back_to_recapture(self) -> None:
        """Truncation or a linked seal is corruption, not absent optional evidence."""
        render = self.capture()
        seal = self.f.root / 'capture-stage.json'
        original = seal.read_bytes()
        for content in (b'{', b'{}'):
            seal.write_bytes(content)
            with self.subTest(content=content), self.assertRaises((ValueError, KeyError)):
                prepare_reverification(self.f.current(), render)
        seal.unlink()
        target = self.f.base / 'same-seal.json'
        target.write_bytes(original)
        seal.symlink_to(target)
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            prepare_reverification(self.f.current(), render)
        self.assertFalse(Path(self.f.current()['output']).exists())

    def test_successful_unsealed_capture_with_missing_jpeg_cannot_be_replaced(self) -> None:
        """Evidence corruption is terminal even if a fresh capture could otherwise run."""
        render = self.capture()
        (self.f.root / 'capture-stage.json').unlink()
        (self.f.root / 'pose-0.jpg').unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            prepare_reverification(self.f.current(), render)
        self.assertFalse((self.f.root / 'capture-stage.json').exists())

    def test_changed_jpeg_after_admission_stops_before_verification(self) -> None:
        """The prepared request does not authorize later replacement of reference pixels."""
        render = self.capture()
        request = prepare_reverification(self.f.current(), render)
        (self.f.root / 'pose-0.jpg').write_bytes(b'TEST replaced image')
        self.assertFalse(self.execute(request))
        self.assertEqual(self.f.calls, [])
        result = json.loads((Path(request['output']) / 'delivery.json').read_text())
        self.assertEqual(result['status'], 'failed')

    def test_changed_resumed_render_closure_is_rejected(self) -> None:
        """A later attempt cannot replace its render-result pointer with unrelated proof."""
        render = self.capture()
        request = prepare_reverification(self.f.current(), render)
        root = Path(request['output'])
        root.mkdir()
        self.f.write_request({**request, 'renderResult': '/TEST/unrelated-media.json'})
        with self.assertRaisesRegex(ValueError, 'another render closure'):
            prepare_reverification(self.f.current(self.f.base / 'next'), render, root)

    def test_batch_capture_uses_same_recovery_contract_and_its_worker(self) -> None:
        """Batch capture sealing retains Python worker identity and original route."""
        self.f.request['captureMode'] = 'cached-native-batches'
        render = self.capture()
        with mock.patch('studio.native_short_resume.picture_reuse_pins', return_value={}):
            request = prepare_reverification(self.f.current(), render)
        self.assertEqual(request['captureMode'], 'cached-native-batches')
        self.assertTrue(self.execute(request))
        self.assertEqual([name for name, _ in self.f.calls], ['verification'])

    def test_incomplete_owner_or_mutated_ordered_schedule_cannot_seal(self) -> None:
        """Success labels cannot replace cleanup, worker identity or exact occurrences."""
        render = self.capture()
        (self.f.root / 'capture-stage.json').unlink()
        owner_file = self.f.root / 'capture.render.json'
        owner = json.loads(owner_file.read_text())
        write_json(owner_file, {**owner, 'leaseCleanupVerified': False})
        with self.assertRaisesRegex(ValueError, 'leaseCleanupVerified'):
            prepare_reverification(self.f.current(), render)
        write_json(owner_file, owner)
        native_file = self.f.root / 'native-frames.json'
        native = json.loads(native_file.read_text())
        native['expectedCapturePoints'] = [24, 0, 0]
        write_json(native_file, native)
        with self.assertRaisesRegex(ValueError, 'schedule differs'):
            prepare_reverification(self.f.current(), render)

    def test_prepare_cli_selects_explicit_attempt_and_requires_fresh_output(self) -> None:
        """The public exporter wires attempt recovery through normal project admission."""
        self.capture()
        args = self.f.options(resume_from=self.f.root)
        with mock.patch('studio.native_short_export.local_environment', return_value=(self.f.request['tools'], {})), \
                mock.patch('studio.native_short_export.subprocess.run'), \
                mock.patch('studio.native_short_export.install_runtime', return_value=self.f.runtime), \
                mock.patch('studio.native_short_export.reference_snapshot'), \
                mock.patch('studio.native_short_export.input_pins', return_value=self.f.inputs):
            request, _environment = prepare(args)
            self.assertEqual(request['captureStage'], str(self.f.root / 'capture-stage.json'))
            self.assertTrue(Path(request['output']).is_dir())
            with self.assertRaisesRegex(ValueError, 'new directory'):
                prepare(args)

    def test_resume_from_option_rejects_render_flags_and_other_recovery(self) -> None:
        """Explicit attempt recovery preserves policy rather than combining options."""
        for change in ({'cache': self.f.base / 'cache'}, {'render_only': True},
                       {'verify_from': self.f.root / 'render-stage.json'}):
            args = self.f.options(resume_from=self.f.root, **change)
            with self.subTest(change=change), mock.patch('studio.native_short_export.local_environment') as tools:
                with self.assertRaises(ValueError):
                    prepare(args)
                tools.assert_not_called()
        argv = ['native-short-export', str(self.f.project), str(self.f.base / 'new'),
                '--resume-from', str(self.f.root), '--render-only']
        with mock.patch.object(sys, 'argv', argv), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch('studio.native_short_export.execute') as execute, self.assertRaises(SystemExit):
            main()
        execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()

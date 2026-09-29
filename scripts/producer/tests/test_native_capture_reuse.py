"""Standalone capture seals reused by the first final export; TEST owners, never media quality."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _native_short_pipeline_fixture import ShortPipelineFixture, isolate_early_checks
from studio import native_review_contract as review
from studio.native_capture_reuse import bind_capture_reuse, capture_identity
from studio.native_runtime import digest
from studio.native_short_pipeline import FINAL_STATUS, NativeShortPipeline
from studio.native_short_resume import prepare_reverification, render_stage_for_attempt


class StandaloneCaptureReuseTests(unittest.TestCase):
    """A preview's sealed capture serves the first final; every other difference recaptures."""

    def setUp(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.f = ShortPipelineFixture(base)
        isolate_early_checks(self)
        self.enterContext(mock.patch('studio.native_short_pipeline.NativeRun', side_effect=self.f.owner_factory))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def run_request(self, request: dict, fail: str | None = None) -> bool:
        """Execute the real coordinator; only child media work is TEST-fabricated."""
        Path(request['output']).mkdir(exist_ok=True)
        self.f.write_request(request)
        self.f.failures = {fail: False} if fail else {}
        self.f.calls.clear()
        return NativeShortPipeline(request, {}).execute()

    def preview_only(self) -> Path:
        """The ordinary preview-only invocation: capture, sealed at once, then previews."""
        request = {**copy.deepcopy(self.f.request), 'previewOnly': True}
        self.assertTrue(self.run_request(request))
        self.assertEqual(json.loads((self.f.root / 'delivery.json').read_text())['status'],
                         'native-motion-previews-complete')
        return self.f.root / 'capture-stage.json'

    def final_request(self, name: str = 'final', pins: dict | None = None, **changes: object) -> dict:
        """A later final request with extra review/preview pins that capture never reads."""
        review_file = self.f.base / 'TEST-motion-reviews.json'
        review_file.write_text('{"TEST": "review bundle is not a capture dependency"}')
        request = {**copy.deepcopy(self.f.request), 'output': str(self.f.base / name), **changes}
        request['pins'] = {**(pins or request['pins']), str(review_file): digest(review_file)}
        return bind_capture_reuse(request)

    def test_preview_capture_is_sealed_before_any_preview_or_render(self) -> None:
        seal = self.preview_only()
        self.assertTrue(seal.is_file())
        record = json.loads(seal.read_text())
        self.assertEqual(record['successStatus'], 'native-reference-capture-complete')
        labels = [label for label, _settings in self.f.calls]
        self.assertEqual(labels[0], 'capture')
        self.assertNotIn('pipeline', labels)
        preview_pins = self.f.calls[1][1].additional_pins
        self.assertEqual(preview_pins.get(str(seal)), digest(seal))

    def test_first_final_adopts_preview_capture_and_keeps_output_checks(self) -> None:
        seal = self.preview_only()
        request = self.final_request()
        self.assertEqual(request['captureStage'], str(seal))
        self.assertEqual(request['captureDependencySha256'], capture_identity(request, self.f.request['pins']))
        self.assertTrue(self.run_request(request))
        labels = [label for label, _settings in self.f.calls]
        self.assertNotIn('capture', labels)
        self.assertEqual(labels[-2:], ['pipeline', 'verification'])
        root = Path(request['output'])
        delivery = json.loads((root / 'delivery.json').read_text())
        self.assertEqual(delivery['status'], FINAL_STATUS)
        self.assertEqual(delivery['stages'][0]['phase'], 'capture-reused')
        self.assertEqual(delivery['captureStage'], str(seal))
        self.assertEqual((root / 'native-frames.json').read_bytes(), (self.f.root / 'native-frames.json').read_bytes())
        _delivery, _request, pins = review.checked_delivery(root)
        self.assertEqual(pins[str(seal)], digest(seal))
        (root / 'native-frames.json').write_text('{"TEST": "replaced reference receipt"}')
        with self.assertRaises((ValueError, RuntimeError)):
            review.checked_delivery(root)

    def test_content_code_runtime_or_policy_changes_recapture(self) -> None:
        self.preview_only()
        source = self.f.project / 'index.html'
        original = source.read_text()
        source.write_text('<p>TEST changed composition</p>')
        changed = {**self.f.request['pins'], str(source): digest(source)}
        self.assertNotIn('captureStage', self.final_request('content', changed))
        source.write_text(original)
        code = next(name for name in self.f.request['pins'] if name.endswith('native_short_worker.py'))
        self.assertNotIn('captureStage', self.final_request('code', {**self.f.request['pins'], code: '0' * 64}))
        self.assertNotIn('captureStage', self.final_request('policy', captureMode='cached-native-batches'))
        self.assertNotIn('captureStage', self.final_request('cache', cache=str(self.f.base / 'other-cache')))
        self.assertIn('captureStage', self.final_request('unchanged'))

    def test_caption_suppression_edit_recaptures_pictures(self) -> None:
        """A suppression changes the authored plan bytes, so stale reference pixels are never adopted."""
        self.preview_only()
        plan_file = self.f.project / 'SHORT-PROJECT.json'
        plan = json.loads(plan_file.read_text())
        plan['canvas']['captionSuppressions'] = [{'startFrame': 0, 'endFrame': 10, 'reason': 'TEST title card holds'}]
        plan_file.write_text(json.dumps(plan))
        changed = {**self.f.request['pins'], str(plan_file): digest(plan_file)}
        self.assertNotIn('captureStage', self.final_request('suppressed', changed))

    def test_changed_donor_reference_is_rejected_not_replaced(self) -> None:
        self.preview_only()
        (self.f.root / 'pose-0.jpg').write_bytes(b'TEST replaced reference pixels')
        with self.assertRaises((ValueError, RuntimeError)):
            self.final_request()

    def test_verification_resume_carries_the_adopted_seal(self) -> None:
        seal = self.preview_only()
        request = self.final_request()
        self.assertFalse(self.run_request(request, 'verification'))
        attempt = Path(request['output'])
        self.assertFalse((attempt / 'capture-stage.json').exists())
        resumed = prepare_reverification(self.f.current(self.f.base / 'resumed'), render_stage_for_attempt(attempt), attempt)
        self.assertEqual((resumed['captureStage'], resumed['captureDependencySha256']),
                         (str(seal), request['captureDependencySha256']))
        self.assertTrue(self.run_request(resumed))
        self.assertEqual([label for label, _settings in self.f.calls], ['verification'])
        review.checked_delivery(Path(resumed['output']))

    def test_a_different_project_seal_is_never_adopted(self) -> None:
        self.preview_only()
        other = self.f.base / 'other-project'
        other.mkdir()
        for file in self.f.project.iterdir():
            (other / file.name).write_bytes(file.read_bytes())
        pins = {name.replace(str(self.f.project), str(other)): sha for name, sha in self.f.request['pins'].items()}
        request = bind_capture_reuse({**copy.deepcopy(self.f.request), 'project': str(other),
                                      'output': str(self.f.base / 'other-final'), 'pins': pins})
        self.assertNotIn('captureStage', request)


if __name__ == '__main__':
    unittest.main()

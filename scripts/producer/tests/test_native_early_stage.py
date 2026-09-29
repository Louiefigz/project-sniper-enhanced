"""Pre-capture static and audio gates: ordering, early failure and exact static reuse."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _native_current_source_fixture import bind_test_motion_previews, isolated_gates, test_source_request, write_test_json
from _native_short_pipeline_fixture import ShortPipelineFixture
from graphics.visual_source_project import describe_project
from studio import native_early_stage as early
from studio import native_short_worker as worker
from studio.native_audio_stage import AudioStageFailure
from studio.native_preflight import preflight
from studio.native_runtime import digest
from studio.native_short_pipeline import FINAL_STATUS, NativeShortPipeline
from test_native_preflight import HTML


class EarlyGateOrderTests(unittest.TestCase):
    """The real coordinator runs static and audio gates before any TEST media owner."""

    def setUp(self) -> None:
        """Patch only child execution, the SDK lint and the audio DSP stage."""
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.f = ShortPipelineFixture(base)
        self.enterContext(mock.patch('studio.native_short_pipeline.NativeRun', side_effect=self.f.owner_factory))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.order: list[str] = []
        self.static_status = 'static-checks-pass'
        self.enterContext(mock.patch.object(early, 'preflight', side_effect=self.fake_preflight))
        self.stage = self.enterContext(mock.patch.object(early, 'prepare_stage', side_effect=self.fake_stage))
        self.enterContext(mock.patch.object(early, 'read_sealed_stage', side_effect=self.fake_record))
        self.diagnostics = {'schemaVersion': 1, 'status': 'clean', 'reverseSeek': {'status': 'reverse-seek-stable'},
                            'phoneText': {'elementCount': 0}}
        self.enterContext(mock.patch('studio.native_capture_diagnostics.capture_diagnostics',
                                     side_effect=lambda *_args: self.diagnostics))
        root = self.f.root
        self.f.request['audioStage'] = {'mode': 'attempt', 'audioInputSha256': 'a' * 64,
                                        'seal': str(root / 'audio-stage/audio-stage.json'), 'sealSha256': None}
        self.f.write_request(self.f.request)

    def fake_preflight(self, project: Path, output: Path, reference: Path | None) -> dict:
        """Write the three evidence files a completed preflight leaves behind."""
        self.order.append('static-preflight')
        output.mkdir()
        for name in early.STATIC_FILES:
            write_test_json(output / name, {'TEST': name, 'status': self.static_status})
        return {'status': self.static_status}

    def fake_stage(self, plan: object, environment: dict) -> dict:
        """Model a sealed stage's small receipts; DSP is covered elsewhere."""
        self.order.append('audio-stage')
        plan.root.mkdir()
        for name in ('audio-stage.json', 'stage-request.json', 'audio-stage.render.json',
                     'audio-stage-result.json', 'receipt.json'):
            write_test_json(plan.root / name, {'TEST': name})
        self.assertEqual((plan.work_seconds, plan.capacity_wait_seconds), early.audio_stage_allowance({}))
        return {}

    def fake_record(self, seal: Path, identity: str) -> dict:
        """Return a seal view whose small bound files exist on disk."""
        root = seal.parent
        files = {'request': 'stage-request.json', 'owner': 'audio-stage.render.json',
                 'result': 'audio-stage-result.json', 'masterReceipt': 'receipt.json'}
        return {'status': 'native-audio-stage-sealed', 'master': {'sha256': 'b' * 64},
                **{key: {'path': str(root / name), 'sha256': digest(root / name)} for key, name in files.items()}}

    def delivery(self) -> dict:
        """Read the coordinator's terminal receipt."""
        return json.loads((self.f.root / 'delivery.json').read_text())

    def test_static_then_audio_precede_every_capture_and_picture_owner(self) -> None:
        """Stage receipts show static preflight and audio before capture, previews and picture."""
        self.assertTrue(NativeShortPipeline(self.f.request, {'TEST_ONLY': '1'}).execute())
        phases = [row['phase'] for row in self.delivery()['stages']]
        self.assertEqual(phases[:4], ['static-preflight', 'audio-stage', 'capture', 'capture-diagnostics'])
        self.assertEqual(self.order, ['static-preflight', 'audio-stage'])
        self.assertEqual(self.delivery()['status'], FINAL_STATUS)

    def test_blocked_package_fails_before_audio_capture_or_picture(self) -> None:
        """A missing dependency/blocked lint result stops the export with no owner started."""
        self.static_status = 'blocked'
        self.assertFalse(NativeShortPipeline(self.f.request, {'TEST_ONLY': '1'}).execute())
        result = self.delivery()
        self.assertEqual((result['failedPhase'], result['failureCategory']), ('static-preflight', 'early-check-failure'))
        self.assertEqual([row['phase'] for row in result['stages']], ['static-preflight'])
        self.assertEqual(self.f.calls, [])
        self.stage.assert_not_called()

    def test_failed_audio_stage_stops_before_capture_or_picture(self) -> None:
        """A bad audio finishing/profile outcome fails at the audio stage; no media owner runs."""
        self.stage.side_effect = AudioStageFailure({'error': 'Early native float master failed shared audio '
                                                             'quality checks'})
        self.assertFalse(NativeShortPipeline(self.f.request, {'TEST_ONLY': '1'}).execute())
        result = self.delivery()
        self.assertEqual((result['failedPhase'], result['failureCategory']), ('audio-stage', 'audio-stage-failure'))
        self.assertIn('audio quality checks', result['error'])
        self.assertEqual([row['phase'] for row in result['stages']], ['static-preflight', 'audio-stage'])
        self.assertEqual(self.f.calls, [])

    def test_refused_audio_worker_names_its_refusal_in_the_delivery(self) -> None:
        """An owner-gate refusal reaches delivery.json as the error and category, not a failed check."""
        reason = 'Native audio worker refused: its supervisor is not alive as its parent'
        self.stage.side_effect = AudioStageFailure({'error': reason, 'failureCategory': 'audio-owner-refused',
                                                    'workerRefused': True})
        self.assertFalse(NativeShortPipeline(self.f.request, {'TEST_ONLY': '1'}).execute())
        result = self.delivery()
        self.assertEqual((result['failedPhase'], result['failureCategory']), ('audio-stage', 'audio-owner-refused'))
        self.assertIn(reason, result['error'])
        self.assertEqual(self.f.calls, [])

    def test_reverse_seek_drift_stops_a_full_export_before_previews(self) -> None:
        """Captured-reference drift fails a reviewed export before any preview or picture owner."""
        self.diagnostics = {**self.diagnostics, 'status': 'defects',
                            'reverseSeek': {'status': 'reverse-seek-drift', 'failed': [{'frame': 24}]}}
        request = {**self.f.request, 'previewOnly': False}
        self.f.write_request(request)
        self.assertFalse(NativeShortPipeline(request, {'TEST_ONLY': '1'}).execute())
        result = self.delivery()
        self.assertEqual(result['failedPhase'], 'reverse-seek')
        self.assertEqual([label for label, _ in self.f.calls], ['capture'])

    def test_reverse_seek_drift_is_recorded_without_blocking_preview_only_review(self) -> None:
        """Editorial previews still render; the finding is visible in the delivery stages."""
        self.diagnostics = {**self.diagnostics, 'status': 'defects',
                            'reverseSeek': {'status': 'reverse-seek-drift', 'failed': [{'frame': 24}]}}
        request = {**self.f.request, 'previewOnly': True}
        self.f.write_request(request)
        self.assertTrue(NativeShortPipeline(request, {'TEST_ONLY': '1'}).execute())
        row = next(row for row in self.delivery()['stages'] if row['phase'] == 'capture-diagnostics')
        self.assertEqual((row['status'], row['reverseSeek']), ('defects', 'reverse-seek-drift'))

    def test_resumed_verification_skips_early_gates(self) -> None:
        """A sealed-render verification attempt neither relints nor re-prepares audio."""
        pipeline = NativeShortPipeline({**self.f.request, 'verifyStage': '/TEST/render-stage.json'}, {})
        early.run_early_checks(pipeline)
        self.assertEqual(self.order, [])


def short_sources(project: Path) -> dict:
    """Explicit TEST reference decision for an inert Short, embedded in its plan."""
    receipt = describe_project(project)
    request, reference = test_source_request(project)
    receipt.pop('sourceEvidenceChecked')
    receipt.update(request=request, decisions=[{'route': 'reference', 'targets': receipt['targets'],
        'reference': reference, 'reason': 'The TEST request explicitly selects this inert dependency fixture.',
        'adaptation': 'TEST static lint fixture only; no media, review or quality is asserted.'}])
    return receipt


class StaticReuseTests(unittest.TestCase):
    """render_media reuses an exactly current early pass and reruns when inputs drift."""

    def setUp(self) -> None:
        """A real lintable TEST project with the actual installed SDK preflight."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.project, self.root = self.base / 'project', self.base / 'attempt'
        (self.project / 'assets').mkdir(parents=True)
        self.root.mkdir()
        (self.project / 'index.html').write_text(HTML)
        (self.project / 'assets/gsap.js').write_text('throw Error("TEST source must never execute");')
        (self.project / 'assets/test.woff2').write_bytes(b'TEST FONT PLACEHOLDER, NOT QUALIFIED FONT DATA')
        (self.project / 'assets/mark.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.plan = {'canvas': {'frameRate': '25/1', 'totalFrames': 25, 'text': [], 'shapes': [],
                                'captionViews': [{'startFrame': 0, 'endFrame': 25}]}}
        write_test_json(self.project / 'SHORT-PROJECT.json', self.plan)
        self.plan['visualSources'] = short_sources(self.project)
        write_test_json(self.project / 'SHORT-PROJECT.json', self.plan)
        node = os.environ.get('SNIPER_NODE_PATH') or shutil.which('node')
        self.assertIsNotNone(node, 'Installed local Node is required; never download it')
        self.enterContext(mock.patch.dict(os.environ, {'SNIPER_NODE_PATH': str(Path(node).resolve())}))
        self.early = preflight(self.project, self.root / 'static')
        self.assertEqual(self.early['status'], 'static-checks-pass')

    def test_current_early_pass_is_reused_and_drift_forces_a_rerun(self) -> None:
        """Identical source/validator/reference state reuses; a changed asset does not."""
        reused = early.reusable_static_result(self.project, self.root, None)
        self.assertEqual(reused['sourceStateSha256'], self.early['sourceStateSha256'])
        self.assertEqual(reused['reusedEarlyResult'], str(self.root / 'static'))
        (self.project / 'assets/mark.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><g/></svg>')
        self.assertIsNone(early.reusable_static_result(self.project, self.root, None))

    def test_render_media_gate_uses_the_early_result_without_relinting(self) -> None:
        """The in-render gate still runs, but an unchanged early pass is not repeated."""
        request = {'output': str(self.root), 'project': str(self.project), 'pins': {},
                   'tools': {'node': os.environ['SNIPER_NODE_PATH']}, 'runtime': str(self.base / 'runtime'),
                   'cache': str(self.base / 'cache')}
        bind_test_motion_previews(request)
        self.enterContext(mock.patch('studio.native_stage_evidence.read_native_capture_receipt',
                                     return_value={'status': 'native-references-and-seek-states-pass'}))
        self.enterContext(mock.patch('studio.native_picture_references.check_samples'))
        lint = self.enterContext(mock.patch.object(early, 'preflight'))  # the in-owner gate's fresh run
        self.enterContext(mock.patch.object(worker, 'prepare_source_view'))  # Shared-store view: own tests.
        actual = isolated_gates(self, subprocess.run)  # the real review gate, in private authority roots
        def execute(command: list[str], **kwargs: object) -> object:
            """Keep the real review validator; stop before the picture command."""
            if 'render' in command:
                raise RuntimeError('TEST stop before picture')
            return actual(command, **kwargs)
        with mock.patch('studio.native_short_delivery.prepare_dialogue', return_value={'TEST': True}), \
                mock.patch('subprocess.run', side_effect=execute), \
                self.assertRaisesRegex(RuntimeError, 'TEST stop before picture'):
            worker.render_media(request, self.plan)
        lint.assert_not_called()


if __name__ == '__main__':
    unittest.main()

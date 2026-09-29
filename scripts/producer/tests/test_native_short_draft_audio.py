"""Review drafts and promotions with the sealed audio stage and the early static gate (no isolation).

Only the audio DSP, the supervised owners and SDK lint are TEST stand-ins; request publication,
binding, discovery, seals, early checks and promotion admission are the production code.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _native_audio_stage_fixture import AudioProjectFixture, fake_prepare_dialogue, owner_factory
from _native_current_source_fixture import write_test_json
from studio import native_audio_stage as stage
from studio import native_early_stage as early
from studio.native_short_draft import DRAFT_STATUS
from studio.native_short_draft_export import draft_input_pins
from studio.native_short_draft_worker import static_admission
from studio.native_short_export import select_and_publish


def draft_admission() -> dict:
    """What project_admission() returns for a final-eligible project under --review-draft."""
    return {'reviewDraft': True, 'draftAuthority': {
        'schemaVersion': 1, 'projectReviewState': 'final-eligible', 'projectDraft': None,
        'prebuildReview': {'status': 'TEST'}, 'openFindings': [], 'suppliedFindings': None,
        'editorialReview': 'pending'}}


def args(**values: object) -> argparse.Namespace:
    """Exporter arguments with every option absent unless given."""
    base = dict(audio_stage=None, resume_from=None, verify_from=None, audio_donor=None, picture_donor=None,
                preview_only=False, preview_reviews=None, preview_from=None, review_draft=False, promote_draft=None)
    return argparse.Namespace(**{**base, **values})


class DraftAudioStageTests(unittest.TestCase):
    """A draft prepares or imports sealed audio; a promotion compares project inputs only."""

    def setUp(self) -> None:
        """TEST project, runtime and patched process/DSP boundaries."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.f = AudioProjectFixture(self.base)
        self.runtime = self.base / 'runtime'
        (self.runtime / 'dist').mkdir(parents=True)
        (self.runtime / 'dist/cli.js').write_text('TEST CLI, never executed')
        self.parent = self.base / 'clip'
        self.parent.mkdir()
        self.enterContext(patch('studio.native_run.NativeRun', side_effect=owner_factory(stage.worker)))
        self.enterContext(patch('studio.native_run_config.local_environment', return_value=(self.f.tools, {})))
        self.enterContext(patch.object(stage, 'require_tool_resolution'))
        self.enterContext(patch('studio.native_export_history.history_directory', return_value=self.base / 'history'))
        self.enterContext(patch('studio.native_short_export.hold_source_store_owner', return_value='/TEST/owner.lock'))
        self.enterContext(patch('studio.native_short_delivery.prepare_dialogue', side_effect=fake_prepare_dialogue))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def request(self, name: str, **extra: object) -> dict:
        """The unpublished request prepare() builds."""
        return {'schemaVersion': 1, 'project': str(self.f.project), 'output': str(self.parent / name),
                'runtime': str(self.runtime), 'tools': self.f.tools,
                'cache': str(self.base / 'cache'), 'captureMode': 'sdk-streaming',
                'sourceCacheMode': 'acquire-sdk-preflight', 'audioProfile': 'native-short-v1',
                'pictureDonor': None, 'audioDonor': None, 'preparedMaster': None, 'pins': {}, **extra}

    def test_a_draft_prepares_its_own_stage_before_the_owner_imports_it(self) -> None:
        published = select_and_publish(args(review_draft=True), self.request('draft-v1', **draft_admission()), None)
        self.assertEqual(published['audioStage']['mode'], 'attempt')
        from studio.native_short_pipeline import NativeShortPipeline
        with patch.object(early, 'static_gate'), \
                patch.object(NativeShortPipeline, 'supervise', side_effect=RuntimeError('TEST owner boundary')):
            NativeShortPipeline(published, {}).execute()
        self.assertTrue(Path(published['audioStage']['seal']).is_file())
        from studio.native_short_draft_worker import execute_draft_phase
        with patch('studio.native_short_draft_worker.static_admission', return_value={'staticPreflight': 'TEST'}), \
                patch('studio.native_short_draft_worker.render_draft_picture',
                      side_effect=RuntimeError('TEST stop at picture')):
            with self.assertRaisesRegex(RuntimeError, 'TEST stop at picture'):
                execute_draft_phase(published, 'draft')

    def test_a_draft_that_imported_a_stage_stays_promotable(self) -> None:
        with patch('studio.native_short_delivery.prepare_dialogue', side_effect=fake_prepare_dialogue):
            stage.prepare_stage(stage.AudioStagePlan(self.f.project, self.parent / 'audio-v1', runtime=self.runtime))
        published = select_and_publish(args(review_draft=True), self.request('draft-v1', **draft_admission()), None)
        self.assertEqual(published['audioStage']['mode'], 'discovered')
        self.assertEqual(draft_input_pins(published), {})
        draft = self.parent / 'draft-v1'
        (draft / 'delivery.json').write_text(json.dumps({'status': DRAFT_STATUS, 'promotable': True}))
        reviews = self.base / 'TEST-reviews.json'
        reviews.write_text('{"schemaVersion": 1, "reviews": []}')
        with self.assertRaises(FileNotFoundError) as caught:   # past the input comparison: its sealed stage
            select_and_publish(args(promote_draft=draft, preview_reviews=reviews), self.request('final-v1'), None)
        self.assertEqual(Path(caught.exception.filename).name, 'draft-stage.json')


class PromotionStaticGateTests(unittest.TestCase):
    """The promote and draft owners reuse the early static pass instead of colliding with it."""

    def test_owner_gate_after_the_early_gate(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        project, root = base / 'project', base / 'promoted'
        project.mkdir()
        root.mkdir()
        write_test_json(project / 'SHORT-PROJECT.json', {'canvas': {'frameRate': '25/1', 'totalFrames': 25}})
        request = {'project': str(project), 'output': str(root), 'promoteDraft': {'TEST': 'promotion'},
                   'tools': {'node': '/TEST/node'}}
        self.enterContext(patch.dict(os.environ))  # the gate sets SNIPER_NODE_PATH process-wide
        calls = []

        def fake_preflight(_project: Path, output: Path, *_rest: object, **_options: object) -> dict:
            """The early gate's real side effect: preflight() creates its evidence directory."""
            calls.append(output.name)
            output.mkdir(mode=0o700)
            for name in early.STATIC_FILES:
                write_test_json(output / name, {'TEST': name})
            return {'status': 'static-checks-pass'}
        with patch.object(early, 'preflight', side_effect=fake_preflight):
            early.static_gate(SimpleNamespace(root=root, request=request, stages=[], evidence={}))
            with patch.object(early, 'reusable_static_result', return_value=None):  # inputs drifted: rerun
                admitted = static_admission(request)
        self.assertEqual(calls, ['static', 'static-render'])
        self.assertEqual(admitted['staticEvidence'], str(root / 'static-render'))


if __name__ == '__main__':
    unittest.main()

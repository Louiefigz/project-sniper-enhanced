"""Closed draft/promotion launch vocabulary, draft options, worker ordering and visible labels."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from _native_short_draft_fixture import DraftFixture
from _native_short_pipeline_fixture import STUDIO, write_json
from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE
from studio.native_export import validate_export_launch
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest
from studio.native_short_draft import DRAFT_LABEL, DRAFT_OUTPUT, admit_draft_launch, project_review_label
from studio.native_short_draft_export import project_admission, validate_draft_options
from studio import native_short_draft_worker as worker

OUTPUTS = {'capture': 'native-frames.json', 'preview': 'motion-previews.json', 'render': 'review.mp4',
           'verify': 'checks.json', 'draft': DRAFT_OUTPUT, 'promote': 'review.mp4'}


class DraftLaunchVocabularyTests(unittest.TestCase):
    """The shared launch boundary admits draft phases only for their own request kind."""

    def setUp(self) -> None:
        """A short project and request; admission never launches a process."""
        self.enterContext(patch('graphics.visual_source_project.admit_project_sources'))
        self.gate = self.enterContext(patch('studio.native_motion_previews.require_motion_previews'))
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.project = self.root / 'project'; self.project.mkdir()
        (self.project / 'index.html').write_text('TEST authored project, not rendered')
        (self.project / 'SHORT-PROJECT.json').write_text('{}')
        self.output = self.root / 'attempt'; self.output.mkdir()
        runtime = self.root / 'runtime'; (runtime / 'dist').mkdir(parents=True)
        self.cli = runtime / 'dist/cli.js'; self.cli.write_text('TEST SDK')
        self.file = self.output / 'export-request.json'
        self.base = {'project': str(self.project), 'output': str(self.output), 'runtime': str(runtime), 'tools': {}}

    def admit(self, request: dict, phase: str, output: str | None = None) -> dict | None:
        """Write the request and validate the exact production worker command."""
        self.file.write_text(json.dumps(request))
        sandbox, script = STUDIO / 'native_localhost_only.sb', STUDIO / 'native_short_worker.py'
        settings = NativeRunConfig(self.project, self.output, self.cli,
            ['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable, str(script), str(self.file), phase], {},
            {'output': str(self.output / (output or OUTPUTS[phase])), 'sdkSha256': digest(self.cli),
             'sandboxSha256': digest(sandbox)}, additional_pins={str(self.file): digest(self.file), str(script): digest(script)})
        return validate_export_launch(settings)

    def test_review_draft_request_launches_only_the_draft_phase_and_output(self) -> None:
        """No capture, preview, render or verification owner can run under a draft request."""
        draft = {**self.base, 'reviewDraft': True}
        self.assertEqual(self.admit(draft, 'draft'), draft)
        for phase in ('capture', 'preview', 'render', 'verify', 'promote'):
            with self.subTest(phase=phase), self.assertRaisesRegex(ValueError, 'Review-draft|promotion'):
                self.admit(draft, phase)
        with self.assertRaisesRegex(ValueError, 'shared export worker'):
            self.admit(draft, 'draft', 'review.mp4')
        with self.assertRaisesRegex(ValueError, 'Review-draft'):
            self.admit({**draft, 'previewReviews': '/TEST/reviews.json'}, 'draft')
        self.gate.assert_not_called()

    def test_draft_built_project_cannot_launch_final_phases_even_with_a_crafted_request(self) -> None:
        """The launch boundary reads the project's own draft authority, not the request's claim."""
        (self.project / 'SHORT-PROJECT.json').write_text(json.dumps({'draft': {'state': 'review-pending'}}))
        for phase in ('capture', 'preview', 'render', 'verify'):
            with self.subTest(phase=phase), self.assertRaisesRegex(ValueError, 'draft-built project'):
                self.admit(dict(self.base), phase)
        with self.assertRaisesRegex(ValueError, 'draft-built project'):
            self.admit({**self.base, 'promoteDraft': {'draftSha256': 'a' * 64}}, 'promote')
        draft = {**self.base, 'reviewDraft': True}
        self.assertEqual(self.admit(draft, 'draft'), draft)

    def test_ordinary_and_long_requests_cannot_launch_draft_or_promote(self) -> None:
        """The new phases are closed to their own request kinds."""
        with self.assertRaisesRegex(ValueError, 'Review-draft'):
            self.admit(dict(self.base), 'draft')
        with self.assertRaisesRegex(ValueError, 'promotion'):
            self.admit(dict(self.base), 'promote')
        with self.assertRaisesRegex(ValueError, 'Review-draft'):
            admit_draft_launch({**self.base, 'adapter': 'native-long', 'reviewDraft': True}, 'draft')

    def test_promotion_runs_the_preview_review_gate_and_never_renders(self) -> None:
        """'promote' needs current reviews at launch; a render phase is refused outright."""
        promotion = {**self.base, 'promoteDraft': {'draftSha256': 'a' * 64}}
        self.assertEqual(self.admit(promotion, 'promote'), promotion)
        self.assertEqual(self.gate.call_count, 1)
        for phase in ('capture', 'preview', 'verify'):
            self.admit(promotion, phase)
        self.gate.side_effect = ValueError('TEST Moving previews are absent or stale')
        with self.assertRaisesRegex(ValueError, 'absent or stale'):
            self.admit(promotion, 'promote')
        with self.assertRaisesRegex(ValueError, 'launches no picture render'):
            self.admit(promotion, 'render')
        with self.assertRaisesRegex(ValueError, 'both'):
            admit_draft_launch({**promotion, 'reviewDraft': True}, 'draft')


class DraftOptionsAndWorkerTests(unittest.TestCase):
    """Option conflicts fail early; static admission precedes any audio or picture work."""

    def options(self, **changes: object) -> Namespace:
        """Complete exporter namespace with ordinary defaults."""
        values = {'review_draft': False, 'promote_draft': None, 'draft_findings': None, 'audio_donor': None,
                  'picture_donor': None, 'preview_only': False, 'preview_from': None, 'preview_reviews': None,
                  'cache': None, 'cached_native_batches': False, 'acquire_source_cache': False, 'reference_map': None,
                  'audio_profile': NATIVE_SHORT_MASTERING_PROFILE.identity}
        return Namespace(**{**values, **changes})

    def test_conflicting_options_are_refused_before_any_work(self) -> None:
        """Drafts take no previews/reviews/donors; promotions need reviews and keep the draft route."""
        refused = [dict(review_draft=True, preview_reviews=Path('/TEST/r.json')),
                   dict(review_draft=True, audio_donor=Path('/TEST/a.json')), dict(review_draft=True, preview_only=True),
                   dict(promote_draft=Path('/TEST/d')), dict(draft_findings=Path('/TEST/f.json')),
                   dict(promote_draft=Path('/TEST/d'), preview_reviews=Path('/TEST/r.json'), cached_native_batches=True),
                   dict(promote_draft=Path('/TEST/d'), preview_reviews=Path('/TEST/r.json'), audio_profile='default-v3')]
        for change in refused:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_draft_options(self.options(**change))
        validate_draft_options(self.options(review_draft=True, cached_native_batches=True))
        validate_draft_options(self.options(promote_draft=Path('/TEST/d'), preview_reviews=Path('/TEST/r.json')))
        from studio.native_short_export import main
        for argv in (['--review-draft', '--render-only'], ['--review-draft', '--verify-from', '/TEST/s.json'],
                     ['--promote-draft', '/TEST/d', '--resume-from', '/TEST/a']):
            with self.subTest(argv=argv), patch.object(sys, 'argv', ['x', '/TEST/p', '/TEST/o', *argv]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main()

    def test_static_preflight_failure_stops_before_audio_and_picture(self) -> None:
        """A cheap package failure never reaches the expensive draft render."""
        request = {'output': '/TEST/out', 'project': '/TEST/project', 'reviewDraft': True}
        with patch.object(worker, 'static_admission', side_effect=ValueError('TEST blocked')), \
                patch('studio.native_motion_previews.prepare_audio') as audio, \
                patch.object(worker, 'render_draft_picture') as picture, self.assertRaisesRegex(ValueError, 'TEST blocked'):
            worker.render_review_draft(request, {'canvas': {}})
        audio.assert_not_called(); picture.assert_not_called()

    def test_draft_media_uses_final_route_order_and_draft_file_name(self) -> None:
        """Preflight, audio master, picture, AAC/mux, color metadata, then playability."""
        calls: list[str] = []
        def record(name: str, value: object = None) -> object:
            return lambda *args, **kwargs: calls.append(name) or value
        audio = {'audioReviewRequired': False, 'audioQuality': []}
        color = {'output': f'/TEST/out/{DRAFT_OUTPUT}', 'sha256': 'a' * 64}
        with patch.object(worker, 'static_admission', side_effect=record('static', {'staticPreflight': 'TEST'})), \
                patch('studio.native_motion_previews.prepare_audio', side_effect=record('audio', {})), \
                patch('studio.native_short_worker.verify_files'), \
                patch.object(worker, 'render_draft_picture', side_effect=record('picture')), \
                patch.object(worker, 'finish_dialogue', side_effect=record('mux', audio)), \
                patch.object(worker, 'native_srgb_delivery', side_effect=record('color', color)) as srgb, \
                patch.object(worker, 'playability', side_effect=record('play', {'fullAudioVideoDecodePassed': True})), \
                patch.object(worker, 'stage_span', return_value=contextlib.nullcontext()):
            result = worker.render_review_draft({'output': '/TEST/out', 'project': '/TEST/p'}, {'canvas': {}})
        self.assertEqual(calls, ['static', 'audio', 'picture', 'mux', 'color', 'play'])
        self.assertEqual(srgb.call_args.args[2], DRAFT_OUTPUT)
        self.assertEqual((result['reviewState'], result['editorialReview'], result['finalQc']), ('draft', 'pending', 'not-run'))
        self.assertFalse(result['humanApproved'])

    def test_playability_rejects_a_short_or_long_frame_count(self) -> None:
        """A playable file must have exactly the authored frame count."""
        observed = type('Observed', (), {'packets': [(0,)] * 24})()
        with patch.object(worker, 'observe_picture_source', return_value=observed), \
                self.assertRaisesRegex(ValueError, 'frame count'):
            worker.playability(Path('/TEST/review-draft.mp4'), {'frameRate': '25/1', 'totalFrames': 25})


class DraftAdmissionAndLabelTests(unittest.TestCase):
    """Draft-mode admission keeps real findings; every surface labels the draft."""

    def setUp(self) -> None:
        """Private fixture root; output is quiet."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_admission_merges_project_and_supplied_findings_and_validates_them(self) -> None:
        """check-draft output and --draft-findings become the request's immutable draft authority."""
        f = DraftFixture(self.base, 'draft')
        file = self.base / 'TEST-findings.json'
        write_json(file, {'schemaVersion': 1, 'findings': [{'code': 'TEST_TITLE_EXIT', 'severity': 'major',
                   'message': 'TEST unreviewed title exit', 'evidence': ['TEST']}]})
        args = Namespace(review_draft=True, draft_findings=file)
        self.enterContext(patch('studio.native_short_draft_export.subprocess.run', side_effect=f.admission))
        admission = project_admission(args, f.project, ({'node': str(f.node)}, {}), 60)
        self.assertEqual(project_admission(Namespace(review_draft=False), f.project, ({'node': 'x'}, {}), 60), {})
        for bad in ({'code': 'lower', 'severity': 'major', 'message': 'TEST'},
                    {'code': 'TEST_X', 'severity': 'fatal', 'message': 'TEST'},
                    {'code': 'TEST_X', 'severity': 'major', 'message': 'TEST', 'approved': True}):
            file.unlink(); write_json(file, {'schemaVersion': 1, 'findings': [bad]})
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                project_admission(args, f.project, ({'node': str(f.node)}, {}), 60)
        authority = admission['draftAuthority']
        self.assertTrue(admission['reviewDraft'])
        self.assertEqual(authority['projectReviewState'], 'draft')
        self.assertEqual([row['code'] for row in authority['openFindings']], ['TEST_OPEN_ISSUE', 'TEST_TITLE_EXIT'])
        self.assertEqual(authority['suppliedFindings']['path'], str(file))

    def test_studio_and_review_bundle_label_the_draft_without_altering_it(self) -> None:
        """Managed preview reports DRAFT from project state; the bundle keeps the draft file name."""
        project = self.base / 'draft-project'; project.mkdir()
        write_json(project / 'PROJECT-MANIFEST.json', {'reviewState': 'draft'})
        write_json(project / 'SHORT-PROJECT.json', {'draft': {'state': 'review-pending'}})
        before = {file.name: digest(file) for file in project.iterdir()}
        self.assertEqual(project_review_label(project)['label'], DRAFT_LABEL)
        from studio.native_short_draft import review_state_notice
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(review_state_notice(str(project))['reviewState'], 'draft')
        self.assertIn('REVIEW DRAFT', stderr.getvalue())
        self.assertEqual(before, {file.name: digest(file) for file in project.iterdir()})
        write_json(project / 'PROJECT-MANIFEST.json', {}); write_json(project / 'SHORT-PROJECT.json', {})
        self.assertIsNone(project_review_label(project)['label'])
        self.assertEqual(project_review_label(self.base), {})
        from studio.native_review_bundle import local_page, media_name
        row = {'id': 'TestShort', 'title': 'TEST', 'samples': 48000, 'reviewState': 'draft', 'label': DRAFT_LABEL}
        self.assertEqual(media_name(row), 'TestShort.review-draft.mp4')
        page = local_page([row, {**row, 'id': 'Final', 'reviewState': 'checked', 'label': None}])
        self.assertIn(DRAFT_LABEL, page)
        self.assertIn('src="media/TestShort.review-draft.mp4"', page)
        self.assertIn('src="media/Final.mp4"', page)
        self.assertEqual(page.count(DRAFT_LABEL), 1)


if __name__ == '__main__':
    unittest.main()

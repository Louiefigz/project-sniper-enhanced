"""Consolidated early report, font readiness and the once-per-identity route canary."""
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

from _native_current_source_fixture import write_test_json
from studio import native_early_checks as checks
from studio import native_route_canary as canary
from studio.native_audio_stage import AudioStageFailure
from studio.native_font_readiness import font_readiness
from studio.native_runtime import REPO, digest
from test_native_early_stage import short_sources
from test_native_preflight import HTML

FONT = REPO / 'assets/fonts/Inter-Bold.ttf'
FACE = "<style>@font-face{font-family:Inter;src:url('assets/Inter-Bold.ttf');font-weight:700}</style>"


class FontProjectCase(unittest.TestCase):
    """A lintable TEST Short whose captions/title use one staged Inter face."""

    def setUp(self) -> None:
        """Stage real Inter bytes and inert composition assets."""
        self.assertIsNotNone(shutil.which('fc-query'), 'fontconfig fc-query is required for font readiness')
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.project = self.base / 'project'
        (self.project / 'assets').mkdir(parents=True)
        html = HTML.replace("@font-face{font-family:'TestFont';src:url('assets/test.woff2')}\n", '')
        self.assertNotIn('TestFont', html)
        (self.project / 'index.html').write_text(html.replace('</head>', FACE + '</head>'))
        for name, value in (('gsap.js', 'throw Error("TEST never executes");'), ('test.woff2', 'TEST placeholder'),
                            ('mark.svg', '<svg xmlns="http://www.w3.org/2000/svg"/>')):
            (self.project / 'assets' / name).write_text(value)
        shutil.copyfile(FONT, self.project / 'assets/Inter-Bold.ttf')
        self.write_plan(['TEST', 'captions', 'café'])

    def write_plan(self, words: list[str]) -> None:
        """Author occurrences and a title, then bind explicit TEST source decisions."""
        occurrences = [[index, 0, index, index, index + 1, word, 0] for index, word in enumerate(words)]
        self.plan = {'canvas': {'frameRate': '25/1', 'totalFrames': 25, 'text': [], 'shapes': [],
                                'occurrences': occurrences, 'captionViews': [{'startFrame': 0, 'endFrame': 25}]},
                     'catalogTitle': {'copy': {'text': 'TEST title — ready'}}}
        write_test_json(self.project / 'SHORT-PROJECT.json', self.plan)
        self.plan['visualSources'] = short_sources(self.project)
        write_test_json(self.project / 'SHORT-PROJECT.json', self.plan)


class FontReadinessTests(FontProjectCase):
    """Declared faces must be staged, parseable and cover every rendered character."""

    def test_staged_face_covering_all_text_is_ready(self) -> None:
        """Latin captions and the title's dash are covered by staged Inter Bold."""
        report = font_readiness(self.project)
        self.assertEqual(report['status'], 'fonts-ready', report['defects'])
        self.assertIn('Inter', report['faces'][0]['families'])

    def test_uncovered_glyph_missing_and_unreadable_faces_are_defects(self) -> None:
        """A CJK caption, a missing source and non-font bytes each become explicit defects."""
        self.write_plan(['TEST', '漢字'])
        self.assertEqual([row['codepoint'] for row in font_readiness(self.project)['uncovered']],
                         ['U+5B57', 'U+6F22'])
        (self.project / 'assets/Inter-Bold.ttf').write_bytes(b'TEST not a font')
        self.assertIn('font-source-unreadable', {row['code'] for row in font_readiness(self.project)['defects']})
        (self.project / 'assets/Inter-Bold.ttf').unlink()
        self.assertIn('font-source-missing', {row['code'] for row in font_readiness(self.project)['defects']})


class EarlyReportTests(FontProjectCase):
    """One report consolidates static, audio, font and canary findings without quality claims."""

    def setUp(self) -> None:
        """Use the real static preflight and fonts; stub only audio identity/DSP."""
        super().setUp()
        node = os.environ.get('SNIPER_NODE_PATH') or shutil.which('node')
        self.assertIsNotNone(node, 'Installed local Node is required; never download it')
        self.enterContext(mock.patch.dict(os.environ, {'SNIPER_NODE_PATH': str(Path(node).resolve())}))
        self.enterContext(mock.patch('studio.native_audio_contract.audio_input_contract',
                                     return_value={'schemaVersion': 1, 'contract': 'native-short-audio-input-v1'}))
        self.enterContext(mock.patch('studio.native_audio_seal.discover_stage', return_value=None))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_failed_audio_and_missing_canary_are_consolidated(self) -> None:
        """A bad audio choice is a defect in the same report as the static and font results."""
        failure = AudioStageFailure({'error': 'Early native float master failed shared audio quality checks'})
        with mock.patch('studio.native_audio_stage.prepare_stage', side_effect=failure):
            report = checks.early_report(checks.EarlyCheckOptions(self.project, self.base / 'early'))
        self.assertEqual(report['status'], 'defects-found')
        self.assertEqual(report['checks']['staticPreflight']['status'], 'static-checks-pass')
        self.assertEqual(report['checks']['fonts']['status'], 'fonts-ready')
        self.assertEqual([row['code'] for row in report['defects']], ['audio-stage-failed'])
        self.assertFalse(any(report['claims'].values()))
        self.assertEqual(report['checks']['componentSamples']['status'], 'not-run')
        saved = json.loads((self.base / 'early/early-check-report.json').read_text())
        self.assertEqual(saved['defects'], report['defects'])

    def test_blocked_dependency_is_reported_with_its_sdk_finding(self) -> None:
        """A missing local dependency is listed as a static finding before any render."""
        (self.project / 'assets/mark.svg').unlink()
        with mock.patch('studio.native_audio_stage.prepare_stage',
                        return_value={'master': {'sha256': 'a' * 64}, 'audioReviewRequired': False}):
            report = checks.early_report(checks.EarlyCheckOptions(self.project, self.base / 'early'))
        self.assertEqual(report['checks']['staticPreflight']['status'], 'blocked')
        self.assertTrue(any(row['check'] == 'staticPreflight' and 'mark.svg' in json.dumps(row)
                            for row in report['defects']))


class CanaryTests(unittest.TestCase):
    """The canary admits only TEST fixtures and reuses a verified pass for its identity."""

    def setUp(self) -> None:
        """Create a TEST fixture manifest with a project directory inside it."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.project = self.root / 'projects/good'
        self.project.mkdir(parents=True)
        self.manifest = {'schemaVersion': 1, 'scope': canary.FIXTURE_SCOPE, 'productionAuthority': False,
                         'variants': {'good': {'project': str(self.project), 'totalFrames': 150}}}
        write_test_json(self.root / 'FIXTURE.json', self.manifest)
        self.enterContext(mock.patch.object(canary, 'canary_identity', return_value=('d' * 64, {'repo:x': 'e' * 64})))

    def test_non_test_fixture_or_escaping_project_is_refused(self) -> None:
        """Production projects cannot receive generated TEST review records."""
        write_test_json(self.root / 'FIXTURE.json', {**self.manifest, 'productionAuthority': True})
        with self.assertRaisesRegex(ValueError, 'TEST native route fixture'):
            canary.fixture_project(self.root)
        outside = {**self.manifest, 'variants': {'good': {'project': str(self.root.parent), 'totalFrames': 1}}}
        write_test_json(self.root / 'FIXTURE.json', outside)
        with self.assertRaisesRegex(ValueError, 'escaped'):
            canary.fixture_project(self.root)

    def test_current_pass_is_reused_without_media_work_and_changed_evidence_is_not(self) -> None:
        """Same identity reuses the recorded pass; altered final bytes require a new run."""
        final = self.root / 'runs/one/final'
        final.mkdir(parents=True)
        write_test_json(final / 'delivery.json', {'status': canary.FINAL_STATUS})
        (final / 'review.mp4').write_bytes(b'TEST mp4 bytes')
        record = {'status': canary.PASS_STATUS, 'identity': 'd' * 64, 'final': {'attempt': str(final),
                  'deliverySha256': digest(final / 'delivery.json'), 'reviewSha256': digest(final / 'review.mp4')}}
        (self.root / 'canary-passes').mkdir()
        write_test_json(self.root / 'canary-passes' / f"{'d' * 64}.json", record)
        with mock.patch.object(canary, 'export', side_effect=AssertionError('no media work')):
            self.assertTrue(canary.run_canary(self.root, self.root / 'runs/two', canary.CanaryBounds())['reused'])
        self.assertEqual(canary.canary_status(self.root)['status'], 'pass-current')
        (final / 'review.mp4').write_bytes(b'TEST changed mp4')
        self.assertEqual(canary.canary_status(self.root)['status'], 'no-current-pass')

    def test_a_recorded_run_is_reused_by_the_next_invocation(self) -> None:
        """The pass written by a real run carries every binding its reuse check reads."""
        def export(project: Path, attempt: Path, options: list[str], timeout: float) -> dict:
            attempt.mkdir()
            (attempt / 'review.mp4').write_bytes(b'TEST mp4 bytes')
            write_test_json(attempt / 'delivery.json', {'status': 'TEST'})
            clip = {'path': str(attempt / 'review.mp4'), 'sha256': digest(attempt / 'review.mp4'), 'startFrame': 0,
                    'endFrameExclusive': 30}
            write_test_json(attempt / 'motion-previews.json', {'status': canary.PREVIEW_STATUS, 'clips': [clip],
                            'packet': {'project': str(project), 'units': [{'id': 'project', 'hash': 'f' * 64}]}})
            status = canary.FINAL_STATUS if '--preview-reviews' in options else canary.PREVIEW_STATUS
            return {'attempt': str(attempt), 'status': status, 'wallSeconds': 1.0, 'error': None,
                    'deliverySha256': digest(attempt / 'delivery.json')}
        (self.root / 'runs').mkdir()
        with mock.patch.object(canary, 'export', side_effect=export), \
                mock.patch.object(canary, 'verify_final', return_value={'TEST': 'checks'}):
            first = canary.run_canary(self.root, self.root / 'runs/one', canary.CanaryBounds())
        self.assertFalse(first['reused'])
        with mock.patch.object(canary, 'export', side_effect=AssertionError('no media work')):
            self.assertTrue(canary.run_canary(self.root, self.root / 'runs/two', canary.CanaryBounds())['reused'])

    def test_preview_reuse_is_followed_to_the_attempt_that_packaged_audio(self) -> None:
        """A preview that reused an earlier exact preview reports that attempt's sealed audio."""
        earlier, later = self.root / 'runs/a/preview', self.root / 'runs/b/preview'
        earlier.mkdir(parents=True)
        later.mkdir(parents=True)
        write_test_json(earlier / 'prepared-audio.json', {'audioStage': {'masterSha256': 'a' * 64, 'seal': '/TEST/s'}})
        write_test_json(later / 'export-request.json', {'previewFrom': str(earlier / 'motion-previews.json'),
                                                        'previewSectionDonors': {}})
        audio = canary.packaged_audio(later)
        self.assertEqual((audio['masterSha256'], audio['packagedIn']), ('a' * 64, str(earlier)))
        write_test_json(later / 'export-request.json', {'previewSectionDonors': {}})
        with self.assertRaisesRegex(ValueError, 'neither its own nor a reused'):
            canary.packaged_audio(later)

    def test_generated_reviews_are_test_labeled_and_pass_the_real_validator(self) -> None:
        """The TS motion-review validator admits the TEST record only for this preview's units."""
        preview = self.root / 'run/preview'
        preview.mkdir(parents=True)
        packet = {'schemaVersion': 1, 'project': str(self.project), 'units': [{'id': 'project', 'hash': 'f' * 64}]}
        clip = preview / 'window-0' / 'core.mp4'
        clip.parent.mkdir()
        clip.write_bytes(b'TEST window bytes; nobody played them')
        clips = [{'path': str(clip), 'sha256': digest(clip), 'startFrame': 0, 'endFrameExclusive': 60}]
        write_test_json(preview / 'motion-previews.json', {'status': canary.PREVIEW_STATUS, 'packet': packet, 'clips': clips})
        write_test_json(preview / 'export-request.json', {'project': str(self.project)})
        write_test_json(self.root / 'run/packet.json', packet)
        reviews = canary.write_test_reviews(self.root, self.root / 'run', preview)
        node = os.environ.get('SNIPER_NODE_PATH') or shutil.which('node')
        result = subprocess.run([node, '--import', 'tsx', str(REPO / 'scripts/producer/native-short.ts'),
                                 'check-motion-reviews', str(reviews), str(self.root / 'run/packet.json')],
                                cwd=REPO, capture_output=True, text=True, timeout=120, check=True)
        checked = json.loads(result.stdout)
        self.assertEqual((checked['status'], checked['inspection']['typedRows'], checked['inspection']['testFixtureRows']),
                         ('recorded-independent-motion-pass', 0, 1))
        review = json.loads(reviews.read_text())['reviews'][0]
        self.assertTrue(all(row['method'].startswith('TEST') for row in review['inspection']['entries']))
        self.assertTrue(review['reviewer']['identity'].startswith('TEST'))
        self.assertIn('TEST', review['review']['summary'])


if __name__ == '__main__':
    unittest.main()

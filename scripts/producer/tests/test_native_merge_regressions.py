"""Regressions from the integrated-branch review: recovery, discovery and Studio records."""
from __future__ import annotations

import contextlib
import copy
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from types import SimpleNamespace

from _native_short_pipeline_fixture import ShortPipelineFixture, isolate_early_checks, write_json
from studio.native_review_regions import preview_windows, region_packet
from studio.native_run_config import source_hashes
from studio.native_run_lifecycle import owner_succeeded, verify_final_pins
from studio.native_runtime import digest
from studio.native_short_autoresume import recover_automatically
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_preflight_inputs import SERVER_RECORD
from studio.studio_server import SERVER_RECORD_NAME, ServerRecord, write_record


class RecoveryAfterPreviewFailureTests(unittest.TestCase):
    """A final that failed before its render phase leaves nothing to recover and wedges nothing."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.f = ShortPipelineFixture(self.base)
        isolate_early_checks(self)
        self.enterContext(patch('studio.native_export_history.history_directory', return_value=self.base / 'history'))
        self.enterContext(patch('studio.native_short_pipeline.NativeRun', side_effect=self.f.owner_factory))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_final_failed_in_its_preview_phase_does_not_wedge_later_finals(self) -> None:
        reviews = self.base / 'TEST-reviews.json'
        write_json(reviews, {'schemaVersion': 1, 'reviews': []})
        request = {**copy.deepcopy(self.f.request), 'previewOnly': False, 'previewReviews': str(reviews)}
        self.f.write_request(request)
        directory = self.f.root / 'audio-preparation'   # what prepare_audio leaves before the preview owner fails
        directory.mkdir()
        (directory / 'program-master.wav').write_bytes(b'TEST float master')
        write_json(directory / 'receipt.json', {'status': 'float-master-checked-awaiting-aac',
                                                 'masterSha256': digest(directory / 'program-master.wav')})
        self.f.failures = {'preview': False}
        self.assertFalse(NativeShortPipeline(request, {}).execute())
        self.assertFalse((self.f.root / 'pipeline.render.json').exists())
        current = self.f.current(self.base / 'final-retry')
        recovered = recover_automatically(current)
        self.assertIsNone((recovered.get('recoverySelection') or {}).get('reused'))


class StudioRecordTests(unittest.TestCase):
    """Studio's and Finder's hidden runtime records are not project inputs."""

    def test_hidden_records_change_no_preview_unit(self) -> None:
        f = ShortPipelineFixture(Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))))
        reviewed = region_packet(f.request)
        write_record(str(f.project), ServerRecord(3990, 4242, 'http://127.0.0.1:3990/#project/project', 'TEST'))
        (f.project / '.DS_Store').write_bytes(b'TEST Finder metadata')
        current = region_packet(f.request)
        self.assertEqual(current['sharedHash'], reviewed['sharedHash'])
        self.assertEqual(preview_windows(current, reviewed), [])

    def test_only_the_named_runtime_records_are_skipped(self) -> None:
        """Any other hidden file (a script's runtime data, a nested server-record name) stays an input."""
        self.assertEqual(SERVER_RECORD, SERVER_RECORD_NAME)
        f = ShortPipelineFixture(Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))))
        (f.project / '.data').mkdir()
        (f.project / '.data/state.json').write_text('{"TEST": 1}')
        (f.project / '.data' / SERVER_RECORD_NAME).write_text('{"TEST": "authored"}')
        (f.project / '.config.json').write_text('{"TEST": 1}')
        reviewed, hashes = region_packet(f.request), source_hashes(f.project)
        self.assertIn('.config.json', hashes)
        (f.project / '.data/state.json').write_text('{"TEST": 2}')
        changed = region_packet(f.request)['sharedHash']
        self.assertNotEqual(changed, reviewed['sharedHash'])
        (f.project / '.data' / SERVER_RECORD_NAME).write_text('{"TEST": "edited"}')
        edited = region_packet(f.request)['sharedHash']
        self.assertNotEqual(edited, changed)
        for folder in ('.data/.waveform-cache', '._data'):  # cache names below the root, AppleDouble-like folders
            (f.project / folder).mkdir()
            (f.project / folder / 'TEST.json').write_text('{"TEST": 1}')
            self.assertNotEqual(region_packet(f.request)['sharedHash'], edited)
            edited = region_packet(f.request)['sharedHash']
        write_record(str(f.project), ServerRecord(3990, 4242, 'http://127.0.0.1:3990/#project/project', 'TEST'))
        self.assertNotIn(SERVER_RECORD_NAME, source_hashes(f.project))

    def test_studio_caches_and_finder_files_change_nothing(self) -> None:
        """Studio's thumbnail, waveform and proxy caches and AppleDouble files are never inputs."""
        f = ShortPipelineFixture(Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))))
        reviewed = region_packet(f.request)
        for cache in ('.thumbnails', '.waveform-cache', '.transcode-cache'):
            (f.project / cache).mkdir()
        for index in range(600):  # past the inventory's 512-file bound: the SDK keeps up to 512 MiB
            (f.project / '.thumbnails' / f'TEST-{index}.jpg.4242.uuid.tmp').write_bytes(b'TEST thumbnail')
        (f.project / '.transcode-cache/.tmp-uuid-key.mp4').write_bytes(b'TEST proxy in progress')
        (f.project / '.waveform-cache/TEST.json').write_text('{"TEST": 1}')
        (f.project / '._index.html').write_bytes(b'TEST AppleDouble metadata')
        self.assertEqual(region_packet(f.request)['sharedHash'], reviewed['sharedHash'])
        self.assertNotIn('._index.html', source_hashes(f.project))

    def test_opening_studio_does_not_fail_a_running_owner(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        project, root = base / 'clip-a', base / 'clip-a-final'
        project.mkdir()
        root.mkdir()
        (project / 'index.html').write_text('<p>TEST composition</p>')
        (project / 'SHORT-PROJECT.json').write_text('{"TEST": true}')
        cli, sandbox = base / 'cli.js', base / 'TEST.sb'
        cli.write_text('TEST')
        sandbox.write_text('TEST')
        output = root / 'review.mp4'
        output.write_bytes(b'TEST media')
        owner = SimpleNamespace(
            project=project, cli=cli, settings=SimpleNamespace(sandbox=sandbox), additional_pins={},
            admission={'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)}, abort_reason=None,
            child=SimpleNamespace(returncode=0), root=root, label='pipeline',
            result={'sourceHashesBefore': source_hashes(project), 'cleanup': {'verified': True},
                    'leaseCleanupVerified': True, 'status': 'running'})
        write_record(str(project), ServerRecord(3990, 4242, 'http://127.0.0.1:3990/#project/clip-a', 'TEST'))
        verify_final_pins(owner)
        self.assertTrue(owner.result['sourceStable'])
        self.assertTrue(owner_succeeded(owner, output))


class EarlyGateNodeTests(unittest.TestCase):
    """The supervisor's early static gate uses the request's admitted Node, not the launcher's env."""

    def test_gate_passes_without_a_launcher_node_variable(self) -> None:
        from _native_current_source_fixture import write_test_json
        from studio import native_early_stage as early
        from test_native_early_stage import short_sources
        from test_native_preflight import HTML
        node = os.environ.get('SNIPER_NODE_PATH') or shutil.which('node')
        self.assertIsNotNone(node, 'an installed Node is required for the real SDK lint')
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        project, root = base / 'project', base / 'attempt'
        (project / 'assets').mkdir(parents=True)
        root.mkdir()
        (project / 'index.html').write_text(HTML)
        (project / 'assets/gsap.js').write_text('throw Error("TEST source must never execute");')
        (project / 'assets/test.woff2').write_bytes(b'TEST FONT PLACEHOLDER, NOT QUALIFIED FONT DATA')
        (project / 'assets/mark.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        plan = {'canvas': {'frameRate': '25/1', 'totalFrames': 25, 'text': [], 'shapes': [],
                           'captionViews': [{'startFrame': 0, 'endFrame': 25}]}}
        write_test_json(project / 'SHORT-PROJECT.json', plan)
        plan['visualSources'] = short_sources(project)
        write_test_json(project / 'SHORT-PROJECT.json', plan)
        request = {'project': str(project), 'tools': {'node': str(Path(node).resolve())}}
        pipeline = SimpleNamespace(root=root, request=request, stages=[], evidence={})
        environment = {key: value for key, value in os.environ.items() if key != 'SNIPER_NODE_PATH'}
        with mock.patch.dict(os.environ, environment, clear=True):
            early.static_gate(pipeline)
        self.assertEqual(pipeline.stages[-1]['status'], 'static-checks-pass')


class StudioDuringPreflightTests(unittest.TestCase):
    """Opening Studio while an export's static gate runs neither fails nor voids the gate."""

    def test_studio_record_during_and_after_the_early_lint(self) -> None:
        from _native_current_source_fixture import write_test_json
        from studio import native_early_stage as early
        from studio import native_preflight
        from test_native_early_stage import short_sources
        from test_native_preflight import HTML
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        project = base / 'project'
        (project / 'assets').mkdir(parents=True)
        (project / 'index.html').write_text(HTML)
        (project / 'assets/gsap.js').write_text('throw Error("TEST source must never execute");')
        (project / 'assets/test.woff2').write_bytes(b'TEST FONT PLACEHOLDER, NOT QUALIFIED FONT DATA')
        (project / 'assets/mark.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        plan = {'canvas': {'frameRate': '25/1', 'totalFrames': 25, 'text': [], 'shapes': [],
                           'captionViews': [{'startFrame': 0, 'endFrame': 25}]}}
        write_test_json(project / 'SHORT-PROJECT.json', plan)
        plan['visualSources'] = short_sources(project)
        write_test_json(project / 'SHORT-PROJECT.json', plan)
        node = str(Path(os.environ.get('SNIPER_NODE_PATH') or shutil.which('node')).resolve())
        root = base / 'final-v1'
        root.mkdir()
        pipeline = SimpleNamespace(root=root, request={'project': str(project), 'output': str(root),
                                                       'tools': {'node': node}}, stages=[], evidence={})
        real_execute = native_preflight._execute

        def studio_opens_meanwhile(*args: object, **kwargs: object) -> object:
            write_record(str(project), ServerRecord(3990, 4242, 'http://127.0.0.1:3990/#project/project', 'T'))
            return real_execute(*args, **kwargs)
        with mock.patch.object(native_preflight, '_execute', side_effect=studio_opens_meanwhile):
            early.static_gate(pipeline)
        self.assertEqual(pipeline.stages[-1]['status'], 'static-checks-pass')
        (project / '.DS_Store').write_bytes(b'TEST Finder metadata')
        with mock.patch.dict(os.environ, {'SNIPER_NODE_PATH': node}):   # the owner's environment
            self.assertIsNotNone(early.reusable_static_result(project, root, None))


class PromotionRecoveryTests(unittest.TestCase):
    """A failed promotion is never an automatic-recovery donor (it has no render to resume)."""

    def test_promotion_attempt_is_not_ranked(self) -> None:
        from studio.native_short_autoresume import matching_attempt
        f = ShortPipelineFixture(Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))))
        promoted = {**copy.deepcopy(f.request), 'promoteDraft': {'TEST': 'promotion'}}
        f.write_request(promoted)
        write_json(f.root / 'delivery.json', {'status': 'failed', 'completedAt': '2026-09-27T12:00:00+00:00',
                                             'stages': [{'phase': 'pipeline', 'status': 'failed'}]})
        self.assertIsNone(matching_attempt(f.current(f.root.parent / 'final-retry'), f.root))


if __name__ == '__main__':
    unittest.main()

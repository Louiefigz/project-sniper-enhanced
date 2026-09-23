"""Interrupt/resume preview sections with real seals and explicitly synthetic media."""
from __future__ import annotations

import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _native_short_pipeline_fixture import ShortPipelineFixture
from studio.native_preview_recovery import bind_section_recovery
from studio.native_preview_sections import section_phase, prepare_sections
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_runtime import digest


class PreviewSectionRecoveryTests(unittest.TestCase):
    """A packaging failure must preserve verified pictures without qualifying delivery."""

    def setUp(self):
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.fixture = ShortPipelineFixture(self.base)
        self.enterContext(patch('studio.native_short_pipeline.NativeRun', side_effect=self.fixture.owner_factory))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def interrupted(self):
        """Only child media work is mocked; the coordinator and seal checks run normally."""
        self.fixture.failures['preview-package-0'] = False
        pipeline = NativeShortPipeline(self.fixture.request, {})
        with self.assertRaisesRegex(RuntimeError, 'preview-package-0'):
            prepare_sections(pipeline)
        self.assertTrue((self.fixture.root / 'preview-picture-0-stage.json').is_file())
        self.assertFalse((self.fixture.root / 'preview-package-0-stage.json').exists())
        return pipeline

    def retry_request(self):
        request = copy.deepcopy(self.fixture.request)
        request['output'] = str(self.base / 'retry')
        bind_section_recovery(request)
        Path(request['output']).mkdir()
        self.fixture.write_request(request)
        return request

    def test_packaging_retry_reuses_completed_picture_without_recapture(self):
        self.interrupted()
        donor = self.fixture.root / 'preview-picture-0.mp4'
        original = digest(donor)
        request = self.retry_request()
        self.fixture.failures.clear()
        self.fixture.calls.clear()
        pipeline = NativeShortPipeline(request, {})
        prepare_sections(pipeline)
        self.assertEqual([label for label, _ in self.fixture.calls], ['preview-package-0'])
        self.assertEqual(pipeline.stages[0]['phase'], 'preview-picture-0-reused')
        self.assertEqual(digest(donor), original)
        self.assertTrue((pipeline.root / 'preview-package-0-stage.json').is_file())
        self.assertFalse((pipeline.root / 'delivery.json').exists())
        self.assertEqual(self.fixture.calls[0][1].capacity_wait_seconds, 600)

    def test_corrupt_matching_checkpoint_is_rejected(self):
        self.interrupted()
        (self.fixture.root / 'preview-picture-0.mp4').write_bytes(b'corrupt')
        with self.assertRaises((ValueError, RuntimeError)):
            self.retry_request()

    def test_changed_inputs_cannot_reuse_old_picture(self):
        self.interrupted()
        source = self.fixture.project / 'index.html'
        source.write_text('<p>changed source</p>')
        self.fixture.request['pins'][str(source)] = digest(source)
        request = self.retry_request()
        self.assertEqual(request['previewSectionDonors'], {})

    def test_failed_cleanup_cannot_become_checkpoint_authority(self):
        self.interrupted()
        file = self.fixture.root / 'preview-picture-0.render.json'
        record = json.loads(file.read_text())
        record['cleanup']['verified'] = False
        file.write_text(json.dumps(record))
        with self.assertRaises((ValueError, RuntimeError)):
            self.retry_request()

    def test_missing_or_partial_unsealed_files_are_not_reused(self):
        (self.fixture.root / 'preview-picture-0.json').write_text('{incomplete')
        request = self.retry_request()
        self.assertEqual(request['previewSectionDonors'], {})

    def test_unsealed_picture_receipt_cannot_enter_packaging(self):
        from studio.native_preview_recovery import current_section
        self.fixture.write_section('preview-picture-0', self.fixture.root)
        with self.assertRaises(FileNotFoundError):
            current_section(self.fixture.request, 'preview-picture-0')

    def test_restored_metadata_cannot_change_its_sealed_frame_count(self):
        from studio.native_preview_recovery import restore_section, current_section
        self.interrupted()
        request = self.retry_request()
        pipeline = NativeShortPipeline(request, {})
        restore_section(pipeline, 'preview-picture-0')
        file = pipeline.root / 'preview-picture-0.json'
        value = json.loads(file.read_text())
        value['media']['frames'] += 1
        file.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            current_section(request, 'preview-picture-0')

    def test_phase_parser_rejects_paths_negative_and_unbounded_indexes(self):
        for phase in ['preview-picture--1', 'preview-package-01', 'preview-picture-768', '../preview-picture-0']:
            self.assertIsNone(section_phase(phase))

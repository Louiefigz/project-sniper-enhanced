"""Filesystem-only final-QC recovery checks; no media or resource-owner execution."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _native_short_pipeline_fixture import ShortPipelineFixture, write_json
from studio import resume_final_qc as recovery
from studio.native_runtime import digest
from studio.native_short_pipeline import NativeShortPipeline, FINAL_STATUS
from studio.native_short_resume import prepare_reverification


class FinalQcResumeTests(unittest.TestCase):
    """Actual shared seals qualify retained tiny TEST bytes and unchanged routing."""

    def setUp(self) -> None:
        """Create a valid original media owner and a separately completed capture owner."""
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.f = ShortPipelineFixture(base)
        library = self.f.runtime / 'dist/native-capture-library.mjs'
        library.write_text('TEST SDK capture library')
        for file in (library, recovery.STUDIO / 'native_short_capture.mjs', recovery.STUDIO / 'native_localhost_only.sb'):
            self.f.inputs[str(file)] = digest(file)
        self.f.write_request(self.f.request)
        self.render = self.f.seal()
        self.rows = []
        for index, frame in enumerate([0, 24, 0]):
            image = self.f.root / f'pose-{index}.jpg'
            image.write_bytes(f'TEST JPEG {frame}'.encode())
            self.rows.append({'frame': frame, 'path': str(image), 'sha256': digest(image), 'repeat': index == 2,
                              'payload': [{'path': '/TEST/deleted/frame_00001.png', 'sha256': 'a' * 64}]})
        self.native = {'status': recovery.NATIVE_STATUS, 'fromEncodedOutput': False,
            'project': str(self.f.project), 'failedSceneStates': [], 'width': 1080, 'height': 1920,
            'frameRate': '25/1', 'sourceHtmlSha256': digest(self.f.project / 'index.html'),
            'runtimeLibrarySha256': digest(library), 'expectedCapturePoints': [0, 24, 0], 'frames': self.rows}
        self.file = self.f.root / 'native-frames.json'
        write_json(self.file, self.native)
        request_file = self.f.root / 'export-request.json'
        pins = {**self.f.inputs, str(request_file): digest(request_file)}
        self.owner = self.f.owner_record(self.f.request, pins, recovery.CAPTURE_STATUS, str(self.file))
        self.owner['args'] = ['/usr/bin/sandbox-exec', '-f', str(recovery.STUDIO / 'native_localhost_only.sb'),
            str(self.f.node), str(recovery.STUDIO / 'native_short_capture.mjs'), str(request_file)]
        write_json(self.f.root / 'capture.render.json', self.owner)

    def seal(self) -> Path:
        """Seal the real TEST original ownership and JPEG checksum closure."""
        return recovery.seal_capture(self.f.root, self.render)

    def test_seals_every_occurrence_and_never_requires_deleted_png_payloads(self) -> None:
        """The complete forward/reverse frame inventory is reusable without source cache."""
        before = {file: digest(file) for file in self.f.root.rglob('*') if file.is_file()}
        receipt = self.seal()
        record, pins = recovery.read_capture(receipt, self.render)
        self.assertEqual(len(record['artifacts']), 4)
        self.assertTrue(all(row['path'] in pins and pins[row['path']] == row['sha256'] for row in self.rows))
        self.assertFalse(any('/TEST/deleted' in file for file in pins))
        self.assertEqual(before, {file: digest(file) for file in before})
        self.assertEqual(self.seal(), receipt)

    def test_failed_incomplete_cleanup_or_different_worker_cannot_be_sealed(self) -> None:
        """No success label replaces ownership, exact worker or owned cleanup."""
        changes = [{'status': 'failed'}, {'exitCode': 1}, {'cleanup': {'verified': False, 'survivors': []}},
                   {'additionalFilesStable': False}, {'args': ['TEST another worker']}]
        for change in changes:
            write_json(self.f.root / 'capture.render.json', {**self.owner, **change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.seal()
            self.assertFalse((self.f.root / 'capture-stage.json').exists())

    def test_malformed_schedule_source_and_jpeg_proof_rejects(self) -> None:
        """A changed canvas/source, lost occurrence or missing image cannot gain a seal."""
        changes = [{'status': 'failed'}, {'fromEncodedOutput': True}, {'sourceHtmlSha256': 'a' * 64},
                   {'frameRate': '30/1'}, {'frames': self.rows[:-1]}, {'expectedCapturePoints': [0]},
                   {'frames': [{**self.rows[0], 'sha256': 'a' * 64}, *self.rows[1:]]}]
        for change in changes:
            write_json(self.file, {**self.native, **change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.seal()
        write_json(self.file, self.native)
        Path(self.rows[0]['path']).unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.seal()

    def test_replaced_jpeg_or_changed_capture_after_seal_is_rejected(self) -> None:
        """Sealed checksums stay authoritative across retries."""
        receipt = self.seal()
        image = Path(self.rows[0]['path'])
        image.write_bytes(b'TEST replaced JPEG')
        with self.assertRaises((ValueError, RuntimeError)):
            recovery.read_capture(receipt, self.render)
        image.write_bytes(b'TEST JPEG 0')
        write_json(self.file, {**self.native, 'frames': self.rows[:-1]})
        with self.assertRaises((ValueError, RuntimeError)):
            recovery.read_capture(receipt, self.render)

    def test_wrong_render_stage_or_changed_media_is_rejected(self) -> None:
        """Completed capture cannot qualify another rendered output."""
        receipt = self.seal()
        other = self.f.base / 'other'
        other.mkdir()
        second = ShortPipelineFixture(other)
        with self.assertRaises(ValueError):
            recovery.read_capture(receipt, second.seal())
        (self.f.root / 'review.mp4').write_bytes(b'TEST changed final video')
        with self.assertRaises((ValueError, RuntimeError)):
            recovery.read_capture(receipt, self.render)

    def test_capture_copy_is_exact_and_only_normal_final_owner_executes(self) -> None:
        """The inherited pipeline still requires full final decode and checked cleanup."""
        receipt = self.seal()
        request = prepare_reverification(self.f.current(), self.render)
        _record, pins = recovery.read_capture(receipt, self.render)
        request['pins'].update(pins)
        request['captureStage'] = str(receipt)
        root = Path(request['output'])
        root.mkdir()
        self.f.write_request(request)
        with mock.patch('studio.native_short_pipeline.NativeRun', side_effect=self.f.owner_factory), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(recovery.FinalQcPipeline(request, {}).execute())
        self.assertEqual(self.file.read_bytes(), (root / 'native-frames.json').read_bytes())
        self.assertEqual([name for name, _settings in self.f.calls], ['verification'])
        self.assertEqual(json.loads((root / 'delivery.json').read_text())['status'], FINAL_STATUS)
        self.assertIs(recovery.FinalQcPipeline.render, NativeShortPipeline.render)
        self.assertIs(recovery.FinalQcPipeline.verify, NativeShortPipeline.verify)

    def test_capture_from_prior_verify_attempt_binds_the_original_render_seal(self) -> None:
        """The actual SDK picture-reuse route can retain a later successful capture."""
        root = self.f.base / 'previous-verification'
        request = prepare_reverification(self.f.current(root), self.render)
        root.mkdir()
        self.f.write_request(request)
        rows = []
        for index, row in enumerate(self.rows):
            image = root / f'pose-{index}.jpg'
            image.write_bytes(Path(row['path']).read_bytes())
            rows.append({**row, 'path': str(image)})
        native_file = root / 'native-frames.json'
        write_json(native_file, {**self.native, 'frames': rows})
        pins = {**request['pins'], str(root / 'export-request.json'): digest(root / 'export-request.json')}
        owner = self.f.owner_record(request, pins, recovery.CAPTURE_STATUS, str(native_file))
        owner['args'] = [*self.owner['args'][:-1], str(root / 'export-request.json')]
        write_json(root / 'capture.render.json', owner)
        receipt = recovery.seal_capture(root, self.render)
        record, _pins = recovery.read_capture(receipt, self.render)
        self.assertEqual(record['root'], str(root))
        request['renderResult'] = '/TEST/other-media.json'
        self.f.write_request(request)
        with self.assertRaisesRegex(ValueError, 'another render seal'):
            recovery.read_capture(receipt, self.render)

    def test_prepare_uses_normal_export_admission_and_pins_only_new_adapter(self) -> None:
        """Capture evidence extends the new request without altering old render inputs."""
        receipt = self.seal()
        args = Namespace(capture_stage=receipt, render_stage=self.render, output=self.f.base / 'new-final')
        request = prepare_reverification(self.f.current(args.output), self.render)
        with mock.patch.object(recovery, 'prepare', return_value=(request, {})) as prepare:
            result, _environment = recovery.prepare_resume(args)
        options = prepare.call_args.args[0]
        self.assertIsNone(options.verify_from)
        self.assertEqual(options.resume_from, self.f.root)
        self.assertFalse(options.cached_native_batches or options.acquire_source_cache or options.render_only)
        self.assertEqual(result['renderInputs'], self.f.inputs)
        self.assertEqual(result['captureStage'], str(receipt))
        self.assertEqual(result['pins'][str(Path(recovery.__file__))], digest(Path(recovery.__file__)))
        self.assertNotIn(str(Path(recovery.__file__)), self.f.inputs)

    def test_failed_final_owner_never_returns_checked_delivery(self) -> None:
        """Capture reuse does not bypass the normal resource and full-QC owner."""
        receipt = self.seal()
        request = prepare_reverification(self.f.current(), self.render)
        _record, pins = recovery.read_capture(receipt, self.render)
        request['pins'].update(pins)
        request['captureStage'] = str(receipt)
        Path(request['output']).mkdir()
        self.f.write_request(request)
        self.f.failures['verification'] = False
        with mock.patch('studio.native_short_pipeline.NativeRun', side_effect=self.f.owner_factory), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(recovery.FinalQcPipeline(request, {}).execute())
        result = json.loads((Path(request['output']) / 'delivery.json').read_text())
        self.assertEqual(result['status'], 'failed')


if __name__ == '__main__':
    unittest.main()

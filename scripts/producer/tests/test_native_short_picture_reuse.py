"""Tiny filesystem regressions for stage reuse; no playable media or child jobs."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import native_short_picture_reuse as reuse
from studio import native_short_autoresume as automatic
from studio.native_run_config import source_hashes
from studio.native_runtime import digest


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value))


class NativeShortPictureReuseTests(unittest.TestCase):
    """Require independently retained bytes and original before/after supervision."""

    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.project, self.donor, self.output = [self.root / name for name in ('project', 'donor', 'output')]
        self.runtime, self.studio = self.root / 'runtime', self.root / 'studio'
        for folder in (self.project, self.donor, self.output, self.runtime / 'dist', self.studio):
            folder.mkdir(parents=True)
        self.enterContext(patch.object(reuse, 'STUDIO', self.studio))
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'TEST ONLY source, not media')
        self.tools = {key: str(self.root / key) for key in ('node', 'browser', 'ffmpeg', 'ffprobe')}
        for filename in self.tools.values():
            Path(filename).write_bytes(b'TEST ONLY executable identity')
        for filename in reuse.PICTURE_CODE:
            (self.studio / filename).write_text('TEST ONLY picture implementation')
        for filename in reuse.RUNTIME_FILES:
            (self.runtime / 'dist' / filename).write_text('TEST ONLY SDK bytes')
        self.audio = self.studio / 'native_short_delivery.py'
        self.audio.write_text('TEST ONLY old audio implementation')
        self.make_project()
        self.make_request()
        self.make_picture()
        self.make_supervision()

    def make_project(self) -> None:
        """Create the same manifest/plan binding used by ordinary native exports."""
        (self.project / 'index.html').write_text('<div>TEST ONLY unchanged typography</div>')
        (self.project / 'hyperframes.json').write_text('{}')
        self.canvas = {'frameRate': '25/1', 'totalFrames': 2}
        write_json(self.project / 'SHORT-PROJECT.json', {
            'canvas': self.canvas, 'strategy': {'schemaVersion': 2},
            'assets': [{'path': str(self.source), 'sha256': digest(self.source)}]})
        files = [{'file': path.name, 'sha256': digest(path)} for path in self.project.iterdir()]
        write_json(self.project / 'PROJECT-MANIFEST.json', {'files': files})

    def make_request(self) -> None:
        """Retain old audio pins as well as the renderer and source pins."""
        paths = list(self.project.iterdir()) + [self.source, self.audio]
        paths += list((self.runtime / 'dist').iterdir()) + list(self.studio.iterdir())
        paths += [Path(value) for value in self.tools.values()]
        self.previous = {'schemaVersion': 1, 'project': str(self.project), 'output': str(self.donor),
                         'runtime': str(self.runtime), 'tools': self.tools, 'captureMode': reuse.MODE,
                         'pins': {str(path): digest(path) for path in paths}}
        write_json(self.donor / 'export-request.json', self.previous)

    def make_picture(self) -> None:
        """Use tiny distinct screenshot bytes to prove complete original inventory."""
        frames = self.donor / 'batched-native-render/frames'
        compiled = self.donor / 'batched-native-render/compiled/index.html'
        frames.mkdir(parents=True)
        compiled.parent.mkdir()
        compiled.write_text('<div>TEST ONLY compiled</div>')
        rows = []
        for frame in range(2):
            file = frames / f'frame_{frame:06d}.jpg'
            file.write_bytes(f'TEST ONLY frame {frame}'.encode())
            rows.append({'frame': frame, 'path': str(file), 'sha256': digest(file)})
        picture = self.donor / 'picture.mp4'
        picture.write_bytes(b'TEST ONLY encoded picture, not playable media')
        self.picture = {**self.canvas, 'width': 1080, 'height': 1920,
                        'status': 'picture-encoded-awaiting-parent-qc',
                        'project': str(self.project), 'output': str(picture), 'pictureMode': reuse.MODE,
                        'referenceEncoding': 'jpeg95-matching-opaque-render', 'sha256': digest(picture),
                        'sourceHtmlSha256': digest(self.project / 'index.html'),
                        'runtimeLibrarySha256': digest(self.runtime / 'dist/native-capture-library.mjs'),
                        'compiledSha256': digest(compiled), 'frames': rows,
                        'batches': [{'index': 0, 'frames': [0, 1], 'status': 'captured-and-disposed',
                                     'transport': {'errors': 0}, 'sessionClosed': True,
                                     'browserPoolDrained': True, 'serverClosed': True}],
                        'encodeResult': {'exitCode': 0}, 'encoder': {
                            'command': self.tools['ffmpeg'], 'sdkCliSha256': digest(self.runtime / 'dist/cli.js'),
                            'quality': 'high', 'crf': 15, 'preset': 'slow', 'codec': 'h264', 'passes': 1,
                            'pixelFormat': 'yuv420p', 'width': 1080, 'height': 1920}}
        write_json(self.donor / 'batched-picture.json', self.picture)

    def make_supervision(self) -> None:
        """An audio failure does not undo completed and safely cleaned picture work."""
        pins = {**self.previous['pins'], str(self.donor / 'export-request.json'): digest(self.donor / 'export-request.json')}
        self.pipeline = {'status': 'failed', 'project': str(self.project), 'sourceStable': True,
                         'sdkStable': True, 'sandboxStable': True, 'additionalFilesStable': True,
                         'leaseCleanupVerified': True, 'cleanup': {'verified': True, 'survivors': []},
                         'sourceHashesBefore': source_hashes(self.project),
                         'sourceHashesAfter': source_hashes(self.project),
                         'additionalFilePinsBefore': pins, 'additionalFilePinsAfter': dict(pins)}
        write_json(self.donor / 'pipeline.render.json', self.pipeline)

    def request(self) -> dict:
        """The new supervisor pins every donor receipt and current picture input."""
        return {**self.previous, 'output': str(self.output), 'pictureDonor': str(self.donor),
                'pins': {**self.previous['pins'], **reuse.picture_reuse_pins(self.project, self.donor)}}

    def test_verified_picture_copies_exclusively_without_changing_failed_attempt(self) -> None:
        before = {str(path): digest(path) for path in self.donor.rglob('*') if path.is_file()}
        request = self.request()
        result = reuse.reuse_native_picture(request)
        self.assertEqual(result['status'], 'picture-reused-awaiting-parent-qc')
        self.assertFalse(result['pictureRenderedAgain'])
        self.assertFalse(result['humanApproved'])
        self.assertEqual(digest(self.output / 'picture.mp4'), self.picture['sha256'])
        for name in reuse.DONOR_FILES:
            self.assertIn(str(self.donor / name), result['validatedPins'])
        self.assertEqual(before, {str(path): digest(path) for path in self.donor.rglob('*') if path.is_file()})
        with self.assertRaises(FileExistsError):
            reuse.reuse_native_picture(request)

    def test_automatic_batch_picture_reuses_complete_original_frame_inventory(self) -> None:
        """Discovery retains the batch route and consumes its actual independent proof."""
        self.pipeline.update(exitCode=1, pid=10, output=str(self.donor / 'review.mp4'),
            ownerIdentities=[{'pid': 10, 'pgid': 10, 'parent_pid': 9, 'started': 'TEST'}],
            args=['/usr/bin/sandbox-exec', '-f', str(self.studio / 'native_localhost_only.sb'),
                  sys.executable, str(self.studio / 'native_short_worker.py'), str(self.donor / 'export-request.json'), 'render'])
        write_json(self.donor / 'pipeline.render.json', self.pipeline)
        write_json(self.donor / 'delivery.json', {'status': 'failed', 'completedAt': '2026-09-16T12:00:00Z'})
        current = {**self.previous, 'output': str(self.output), 'pins': dict(self.previous['pins'])}
        with patch.object(automatic, 'candidate_attempts', return_value=[self.donor]), \
                patch.object(automatic, 'STUDIO', self.studio):
            selected = automatic.recover_automatically(current)
        self.assertEqual(selected['recoverySelection']['reused'], 'picture')
        self.assertEqual(selected['captureMode'], reuse.MODE)
        self.assertFalse(reuse.reuse_native_picture(selected)['pictureRenderedAgain'])

    def test_audio_only_implementation_changes_do_not_invalidate_picture(self) -> None:
        self.audio.write_text('TEST ONLY fixed audio implementation')
        request = self.request()
        request['pins'][str(self.audio)] = digest(self.audio)
        self.assertNotIn(str(self.audio), reuse.picture_reuse_pins(self.project, self.donor))
        self.assertEqual(reuse.reuse_native_picture(request)['sha256'], self.picture['sha256'])

    def test_changed_source_picture_script_sdk_and_manifest_are_rejected(self) -> None:
        paths = [self.source, self.donor / 'picture.mp4', self.studio / 'native_short_batched_render.mjs',
                 self.studio / 'native_source_cache.mjs',
                 self.runtime / 'dist/cli.js', self.project / 'PROJECT-MANIFEST.json', self.project / 'index.html']
        for path in paths:
            before = path.read_bytes()
            with self.subTest(path=path):
                path.write_bytes(before + b' CHANGED')
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    reuse.picture_reuse_pins(self.project, self.donor)
                path.write_bytes(before)
        self.assertFalse((self.output / 'picture.mp4').exists())

    def test_adaptive_batch_inventory_uses_its_recorded_bound_and_rejects_bad_plans(self) -> None:
        """New short sessions remain complete; historical missing-plan receipts still use 48."""
        self.assertEqual(reuse.batch_size(self.picture), 48)
        self.picture['batchPlan'] = {'schemaVersion': 1, 'rule': 'admitted-source-rgba-v1', 'maximumFrames': 1}
        original = self.picture['batches'][0]
        self.picture['batches'] = [{**original, 'index': frame, 'frames': [frame]} for frame in range(2)]
        write_json(self.donor / 'batched-picture.json', self.picture)
        self.assertEqual(reuse.reuse_native_picture(self.request())['sha256'], self.picture['sha256'])
        for maximum in (0, 49, True, 3):
            self.picture['batchPlan']['maximumFrames'] = maximum
            with self.subTest(maximum=maximum), self.assertRaisesRegex(ValueError, 'session bounds'):
                reuse.verify_inventory(self.donor, self.picture, self.canvas)
        self.picture['batchPlan']['maximumFrames'] = 1
        self.picture['batches'][1]['frames'] = [0]
        with self.assertRaisesRegex(ValueError, 'inventory'):
            reuse.verify_inventory(self.donor, self.picture, self.canvas)

    def test_self_reported_stability_cannot_override_changed_before_after_pins(self) -> None:
        self.pipeline['additionalFilePinsAfter'][str(self.source)] = 'a' * 64
        write_json(self.donor / 'pipeline.render.json', self.pipeline)
        with self.assertRaisesRegex(ValueError, 'before/after'):
            self.request()

    def test_missing_cleanup_and_incomplete_screenshot_inventory_are_rejected(self) -> None:
        original = json.dumps(self.pipeline)
        for change in ({'cleanup': {'verified': True, 'survivors': [123]}}, {'leaseCleanupVerified': False}):
            write_json(self.donor / 'pipeline.render.json', {**self.pipeline, **change})
            with self.assertRaises(ValueError):
                self.request()
        (self.donor / 'pipeline.render.json').write_text(original)
        self.picture['frames'].pop()
        write_json(self.donor / 'batched-picture.json', self.picture)
        with self.assertRaisesRegex(ValueError, 'inventory'):
            self.request()

    def test_current_request_must_pin_donor_evidence_and_use_same_tools_mode_project(self) -> None:
        request = self.request()
        bad = [{**request, 'captureMode': 'sdk-streaming'}, {**request, 'runtime': '/different'},
               {**request, 'pins': {key: value for key, value in request['pins'].items()
                                   if key != str(self.donor / 'pipeline.render.json')}}]
        for value in bad:
            with self.subTest(value=value.get('captureMode')), self.assertRaises(ValueError):
                reuse.reuse_native_picture(value)
        with self.assertRaises(ValueError):
            reuse.picture_reuse_pins(self.output, self.donor)

    def test_donor_mutation_after_admission_is_rejected_before_copy(self) -> None:
        request = self.request()
        self.picture['newUntrustedLabel'] = 'changed after current pinning'
        write_json(self.donor / 'batched-picture.json', self.picture)
        with self.assertRaisesRegex(ValueError, 'not pinned'):
            reuse.reuse_native_picture(request)
        self.assertFalse((self.output / 'picture.mp4').exists())

    def test_changed_screenshot_bytes_reject_receipt_success_label(self) -> None:
        Path(self.picture['frames'][0]['path']).write_bytes(b'different retained screenshot')
        with self.assertRaisesRegex(ValueError, 'changed input'):
            self.request()

    def test_picture_geometry_and_clock_must_match_fixed_native_contract(self) -> None:
        for key, value in (('width', 1920), ('height', 1080), ('frameRate', '30/1'), ('totalFrames', 3)):
            original = self.picture[key]
            self.picture[key] = value
            write_json(self.donor / 'batched-picture.json', self.picture)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'geometry|canvas'):
                self.request()
            self.picture[key] = original

    def test_changed_donor_during_copy_fails_without_qualifying_partial_output(self) -> None:
        request, original_copy = self.request(), reuse.shutil.copyfileobj

        def mutate_after_copy(reader, writer, length):
            original_copy(reader, writer, length)
            (self.donor / 'picture.mp4').write_bytes(b'TEST ONLY mutation during copy')

        with patch.object(reuse.shutil, 'copyfileobj', side_effect=mutate_after_copy):
            with self.assertRaisesRegex(ValueError, 'changed while copied'):
                reuse.reuse_native_picture(request)
        self.assertEqual((self.output / 'picture.mp4').read_bytes(), b'TEST ONLY encoded picture, not playable media')

    def test_symlinked_screenshot_directory_cannot_substitute_external_evidence(self) -> None:
        frames = self.donor / 'batched-native-render/frames'
        external = self.root / 'outside-frames'
        frames.rename(external)
        frames.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'not the recorded donor output'):
            self.request()


if __name__ == '__main__':
    unittest.main(verbosity=2)

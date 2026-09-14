"""Failure boundaries for local runtime reuse and reverse-seek measurements."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from studio.native_runtime import apply_bytes, digest
from studio.native_short_delivery import finish_dialogue, qualify_reverse_frames
from audio.mastering_profile import LEGACY_MASTERING_PROFILE, NATIVE_SHORT_MASTERING_PROFILE
from studio.native_short_export import REPO, assert_admitted_pins, input_pins, source_cache_mode
from studio.native_short_worker import render_command, verify_files


class NativeRuntimeTests(unittest.TestCase):
    """Reject executable drift and actual picture/scene changes."""

    def test_cold_cache_is_explicit_and_requires_bounded_batches(self):
        """Existing export requests cannot silently trigger additional extraction work."""
        from argparse import Namespace
        self.assertEqual(source_cache_mode(Namespace(cached_native_batches=False)), 'existing-only')
        self.assertEqual(source_cache_mode(Namespace(cached_native_batches=True,
                         acquire_source_cache=True)), 'acquire-sequential-sdr')
        with self.assertRaisesRegex(ValueError, '--cached-native-batches'):
            source_cache_mode(Namespace(cached_native_batches=False, acquire_source_cache=True))

    def test_export_profile_reaches_delivery_before_media_work(self):
        """Default and explicit legacy retain distinct processing and reuse authority."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / 'reference.wav'
            reference.write_bytes(b'unit reference')
            (root / 'picture.mp4').write_bytes(b'unit picture')
            request = {'output': directory, 'project': directory,
                       'tools': {'ffmpeg': '/test/ffmpeg', 'ffprobe': '/test/ffprobe'}}
            canvas = {'frameRate': '25/1', 'totalFrames': 25,
                      'segments': [{'startFrame': 0, 'endFrameExclusive': 25}]}
            for profile in (NATIVE_SHORT_MASTERING_PROFILE, LEGACY_MASTERING_PROFILE):
                chosen = request if profile == NATIVE_SHORT_MASTERING_PROFILE else {
                    **request, 'audioProfile': profile.identity}
                with mock.patch('studio.native_short_delivery.dialogue_reference', return_value=reference), \
                        mock.patch('studio.native_short_delivery.normalize_dialogue_reference', return_value=reference), \
                        mock.patch('studio.native_short_delivery.finish_native_dialogue') as finish:
                    finish_dialogue(chosen, canvas)
                self.assertEqual(finish.call_args.args[0].profile, profile)
                self.assertEqual(finish.call_args.args[0].samples, 48000)
            with mock.patch('studio.native_short_delivery.dialogue_reference') as extract, \
                    self.assertRaises(ValueError):
                finish_dialogue({**request, 'audioProfile': 'unknown'}, canvas)
            extract.assert_not_called()

    def test_shared_audio_policy_drift_is_bound_to_the_export_attempt(self):
        """A changed mastering policy cannot retain an otherwise stable audio module pin."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'PROJECT-MANIFEST.json').write_text(json.dumps({'files': []}))
            (root / 'SHORT-PROJECT.json').write_text(json.dumps({
                'strategy': {'schemaVersion': 2}, 'assets': [],
                'canvas': {'frameRate': '25/1', 'totalFrames': 25}}))
            pins = input_pins(root, root / 'sdk', {})
            policy = REPO / 'scripts/producer/producer_config.py'
            self.assertEqual(pins[str(policy)], digest(policy))
            changed = lambda file: '0' * 64 if file == policy else pins[str(file)]
            with mock.patch('studio.native_short_worker.digest', side_effect=changed), \
                    self.assertRaisesRegex(RuntimeError, 'producer_config.py'):
                verify_files({'pins': pins})

    def test_browser_rotation_is_explicit_and_cannot_silently_replace_the_sdk_route(self):
        """Legacy requests keep their route; unsupported mode names never fall back."""
        request = {'tools': {'node': '/test/node'}, 'runtime': '/test/sdk',
                   'output': '/test/output', 'project': '/test/project', 'cache': '/test/cache'}
        standard = render_command(request, {'frameRate': '25/1'})
        self.assertEqual(standard[1], '/test/sdk/dist/cli.js')
        self.assertIn('--no-best-effort', standard)
        request['captureMode'] = 'cached-native-batches'
        batched = render_command(request, {'frameRate': '25/1'})
        self.assertTrue(batched[1].endswith('/native_short_batched_render.mjs'))
        self.assertEqual(batched[2], '/test/output/export-request.json')
        request['captureMode'] = 'unqualified-auto-fallback'
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            render_command(request, {'frameRate': '25/1'})

    def test_patch_refuses_a_different_input_or_output(self):
        """A runtime change needs a newly qualified patch, never a fuzzy match."""
        row = {'file': 'test.js', 'baseSha256': hashlib.sha256(b'abc').hexdigest(),
               'sha256': hashlib.sha256(b'axc').hexdigest(),
               'patches': [{'offset': 1, 'remove': 1, 'text': 'x'}]}
        self.assertEqual(apply_bytes(b'abc', row), b'axc')
        with self.assertRaisesRegex(ValueError, 'base changed'):
            apply_bytes(b'abd', row)
        row['sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'patch failed'):
            apply_bytes(b'abc', row)

    def test_reverse_tolerance_does_not_admit_a_missing_word_or_changed_state(self):
        """Small edge rounding is allowed; meaningful text loss and state drift fail."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = Image.new('RGB', (1080, 1920), 'black')
            original.save(root / 'a.png')
            edge = original.copy(); edge.putpixel((100, 100), (1, 1, 1)); edge.save(root / 'b.png')
            rows = [{'frame': 10, 'path': str(root / name), 'sha256': digest(root / name),
                     'repeat': index == 1, 'visualState': {'text': 'word'}, 'payload': []}
                    for index, name in enumerate(['a.png', 'b.png'])]
            self.assertTrue(qualify_reverse_frames({'frames': rows})[0]['passed'])
            rows[1]['visualState'] = {'text': 'different word'}
            with self.assertRaisesRegex(RuntimeError, 'scene/source state'):
                qualify_reverse_frames({'frames': rows})
            rows[1]['visualState'] = rows[0]['visualState']
            edge.paste('white', (100, 100, 150, 130)); edge.save(root / 'b.png')
            rows[1]['sha256'] = digest(root / 'b.png')
            with self.assertRaisesRegex(RuntimeError, 'pixel stability failed'):
                qualify_reverse_frames({'frames': rows})

    def test_changed_origin_cannot_be_adopted_as_a_new_export_pin(self):
        """Hashing changed evidence after preflight cannot replace the admitted digest."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / 'origin.json'
            evidence.write_text('original origin')
            expected_hash = digest(evidence)
            report = root / 'ASSET-USE-REPORT.json'
            report.write_text(json.dumps({'originEvidenceFiles': [
                {'path': str(evidence), 'sha256': expected_hash}]}))
            manifest = {'files': [{'file': report.name, 'sha256': digest(report)}]}
            plan = {'strategy': {'schemaVersion': 3}, 'assets': []}
            pins = {str(report): digest(report), str(evidence): expected_hash}
            assert_admitted_pins(root, plan, manifest, pins)
            evidence.write_text('substituted origin')
            pins[str(evidence)] = digest(evidence)
            with self.assertRaisesRegex(ValueError, 'changed before pinning'):
                assert_admitted_pins(root, plan, manifest, pins)

    def test_project_or_supplied_media_pin_must_match_admitted_identity(self):
        """The same pin boundary covers legacy project bytes and prepared supplemental media."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = root / 'request.json'
            supplied = root / 'supplied.png'
            supplied.write_bytes(b'supplied test data')
            packet.write_text(json.dumps({'sources': [], 'availableSupportingAssets': [
                {'path': str(supplied), 'sha256': digest(supplied)}]}))
            plan = {'strategy': {'schemaVersion': 2}, 'assets': [],
                    'requestPacket': {'path': str(packet), 'sha256': digest(packet)}}
            pins = {str(packet): digest(packet), str(supplied): digest(supplied)}
            assert_admitted_pins(root, plan, {'files': []}, pins)
            pins[str(supplied)] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'changed before pinning'):
                assert_admitted_pins(root, plan, {'files': []}, pins)


if __name__ == '__main__':
    unittest.main()

"""Resume admission and audio/color proof regressions without media execution."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _native_short_pipeline_fixture import ShortPipelineFixture, write_json
from audio.mastering_profile import LEGACY_MASTERING_PROFILE
from studio.native_runtime import digest
from studio.native_short_export import main, prepare, validate_options
from studio.native_short_resume import copy_completed_media, media_result, prepare_reverification
from studio.native_stage_evidence import read_stage


class NativeShortResumeTests(unittest.TestCase):
    """The exact sealed route and qualified final bytes govern later verification."""

    def setUp(self) -> None:
        """Create a tiny TEST stage with real exclusive artifacts and digests."""
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.fixture = ShortPipelineFixture(base)

    def proof(self) -> tuple[dict, dict, dict]:
        """Read the audio/media proof from one valid TEST stage."""
        receipt = self.fixture.seal()
        record, _ = read_stage(receipt, self.fixture.inputs, 'render')
        media = json.loads((self.fixture.root / 'render-result.json').read_text())
        audio = json.loads((self.fixture.root / 'audio/receipt.json').read_text())
        return record, media, audio

    def check_proof(self, original: dict, media: dict, audio: dict) -> dict:
        """Exercise semantic proof validation using exact newly written fixture bytes."""
        record = copy.deepcopy(original)
        for name, value in (('media', media), ('audio', audio)):
            path = Path(record['artifacts'][name]['path'])
            write_json(path, value)
            record['artifacts'][name]['sha256'] = digest(path)
        return media_result(record)

    def test_valid_resume_reconstructs_original_route_cache_and_audio_policy(self) -> None:
        """Defaults from a new CLI invocation cannot replace the old capture inputs."""
        self.fixture.request['audioProfile'] = LEGACY_MASTERING_PROFILE.identity
        self.fixture.write_request(self.fixture.request)
        receipt = self.fixture.seal()
        current = {**self.fixture.current(), 'cache': '/TEST/unselected-cache'}
        result = prepare_reverification(current, receipt)
        for key in ('captureMode', 'cache', 'audioProfile', 'tools', 'runtime', 'project'):
            self.assertEqual(result[key], self.fixture.request[key])
        self.assertEqual(result['verifyStage'], str(receipt))
        self.assertEqual(result['renderInputs'], self.fixture.inputs)
        self.assertIn(str(receipt), result['pins'])

    def test_batch_resume_keeps_original_forward_proof_and_donor(self) -> None:
        """A batch receipt is never reinterpreted as a streaming capture route."""
        self.fixture.request['captureMode'] = 'cached-native-batches'
        self.fixture.write_request(self.fixture.request)
        receipt = self.fixture.seal()
        proof = self.fixture.root / 'TEST-batch-proof.json'
        write_json(proof, {'TEST': 'forward proof leaf is mocked'})
        pins = {str(proof): digest(proof)}
        with mock.patch('studio.native_short_resume.picture_reuse_pins', return_value=pins) as reuse:
            result = prepare_reverification(self.fixture.current(), receipt)
        reuse.assert_called_once_with(self.fixture.project, self.fixture.root)
        self.assertEqual(result['captureMode'], 'cached-native-batches')
        self.assertEqual(result['pictureDonor'], str(self.fixture.root))
        self.assertEqual(result['pins'][str(proof)], digest(proof))

    def test_unsupported_original_capture_mode_never_falls_back(self) -> None:
        """Even internally consistent old receipts require a supported native route."""
        self.fixture.request['captureMode'] = 'invented-route'
        self.fixture.write_request(self.fixture.request)
        receipt = self.fixture.seal()
        with self.assertRaisesRegex(ValueError, 'unsupported completed render route'):
            prepare_reverification(self.fixture.current(), receipt)

    def test_project_runtime_and_tools_must_match_completed_media(self) -> None:
        """A valid sealed output cannot be attached to another execution context."""
        receipt = self.fixture.seal()
        alternatives = {'project': str(self.fixture.base), 'runtime': '/TEST/other-runtime',
                        'tools': {'node': '/TEST/other-node'}}
        for key, value in alternatives.items():
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, f'current {key}'):
                prepare_reverification({**self.fixture.current(), key: value}, receipt)

    def test_current_dependency_drift_is_not_reheld_for_resume(self) -> None:
        """Newly collected changed hashes cannot relabel stale completed work."""
        receipt = self.fixture.seal()
        self.fixture.source.write_bytes(b'TEST changed source')
        current = self.fixture.current()
        current['pins'][str(self.fixture.source)] = digest(self.fixture.source)
        with self.assertRaisesRegex(ValueError, 'dependencies differ'):
            prepare_reverification(current, receipt)

    def test_overlapping_donor_destinations_are_rejected_before_copy(self) -> None:
        """A new verification directory may neither overwrite nor contain its donor."""
        receipt = self.fixture.seal()
        for output in (self.fixture.root, self.fixture.root / 'nested', self.fixture.base):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'preserve the donor'):
                prepare_reverification(self.fixture.current(output), receipt)

    def test_exact_final_media_copy_does_not_copy_or_render_picture_audio(self) -> None:
        """The copy operation retains original media proof and writes only final bytes."""
        receipt = self.fixture.seal()
        request = prepare_reverification(self.fixture.current(), receipt)
        output = Path(request['output'])
        output.mkdir()
        record, pins = copy_completed_media(request)
        self.assertEqual([file.name for file in output.iterdir()], ['review.mp4'])
        self.assertEqual(digest(output / 'review.mp4'), record['artifacts']['review']['sha256'])
        self.assertIn(str(receipt), pins)
        with self.assertRaises(FileExistsError):
            copy_completed_media(request)

    def test_unpinned_completed_stage_cannot_be_copied(self) -> None:
        """Resume input preparation cannot be skipped before crossing the copy boundary."""
        receipt = self.fixture.seal()
        request = prepare_reverification(self.fixture.current(), receipt)
        Path(request['output']).mkdir()
        del request['pins'][str(receipt)]
        with self.assertRaisesRegex(ValueError, 'not pinned'):
            copy_completed_media(request)
        self.assertFalse((Path(request['output']) / 'review.mp4').exists())

    def test_changed_output_after_resume_admission_is_rejected_before_copy(self) -> None:
        """A previously prepared request does not authorize changed final MP4 bytes."""
        receipt = self.fixture.seal()
        request = prepare_reverification(self.fixture.current(), receipt)
        output = Path(request['output'])
        output.mkdir()
        (self.fixture.root / 'review.mp4').write_bytes(b'TEST changed final')
        with self.assertRaises((ValueError, RuntimeError)):
            copy_completed_media(request)
        self.assertFalse((output / 'review.mp4').exists())

    def test_missing_audio_or_color_inventory_is_not_a_complete_render(self) -> None:
        """A picture seal alone cannot authorize final audio/video verification."""
        record, media, audio = self.proof()
        for name in ('audio', 'media', 'review', 'picture'):
            incomplete = copy.deepcopy(record)
            del incomplete['artifacts'][name]
            with self.subTest(artifact=name), self.assertRaisesRegex(ValueError, 'inventory'):
                media_result(incomplete)
        with self.assertRaisesRegex(ValueError, 'color/payload'):
            self.check_proof(record, {**media, 'color': {}}, audio)

    def test_audio_and_color_proof_must_match_exact_sealed_artifacts(self) -> None:
        """Conflicting qualification fields cannot be repaired by a valid output hash."""
        record, media, audio = self.proof()
        changes = [{'sha256': 'a' * 64}, {'output': '/TEST/foreign.mp4'},
                   {'audioReceipt': '/TEST/foreign-audio.json'}, {'status': 'failed'}]
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'media proof'):
                self.check_proof(record, {**media, **change}, audio)
        for change in ({'status': 'failed'}, {'audioReviewRequired': True}, {'audioQuality': ['changed']}):
            with self.subTest(audio=change), self.assertRaisesRegex(ValueError, 'audio qualification'):
                self.check_proof(record, media, {**audio, **change})
        for key, value in (('aacPacketsIdentical', False), ('additionalAudioEncodes', 1),
                           ('additionalPictureEncodes', 1), ('sha256', 'a' * 64)):
            with self.subTest(color=key), self.assertRaisesRegex(ValueError, 'color/payload'):
                self.check_proof(record, {**media, 'color': {**media['color'], key: value}}, audio)

    def test_missing_audio_quality_and_review_fields_never_count_as_qualification(self) -> None:
        """Two equally incomplete JSON objects cannot prove completed audio review."""
        record, media, audio = self.proof()
        for key in ('audioQuality', 'audioReviewRequired'):
            missing_media, missing_audio = dict(media), dict(audio)
            del missing_media[key]
            del missing_audio[key]
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, 'audio qualification'):
                self.check_proof(record, missing_media, missing_audio)

    def test_invalid_audio_types_and_boolean_encode_counts_are_rejected(self) -> None:
        """JSON equality must not turn malformed proof fields into valid evidence."""
        record, media, audio = self.proof()
        for key, value in (('audioQuality', {}), ('audioReviewRequired', 0)):
            with self.subTest(audio=key), self.assertRaisesRegex(ValueError, 'audio qualification'):
                self.check_proof(record, {**media, key: value}, {**audio, key: value})
        for key in ('additionalAudioEncodes', 'additionalPictureEncodes'):
            with self.subTest(color=key), self.assertRaisesRegex(ValueError, 'color/payload'):
                self.check_proof(record, {**media, 'color': {**media['color'], key: False}}, audio)

    def test_conflicting_verify_options_reject_before_tools_or_source_reads(self) -> None:
        """Verification reconstructs the original mode rather than combining render options."""
        changes = [{'cache': self.fixture.base / 'cache'}, {'audio_donor': self.fixture.source},
                   {'picture_donor': self.fixture.root}, {'cached_native_batches': True},
                   {'acquire_source_cache': True}, {'audio_profile': LEGACY_MASTERING_PROFILE.identity},
                   {'render_only': True}]
        for change in changes:
            args = self.fixture.options(verify_from=self.fixture.root / 'render-stage.json', **change)
            with self.subTest(change=change), mock.patch('studio.native_short_export.local_environment') as tools, \
                    self.assertRaises(ValueError):
                prepare(args)
            tools.assert_not_called()

    def test_source_and_output_overlap_or_existing_destination_rejects(self) -> None:
        """A new attempt may not replace or live inside the authored project."""
        for output in (self.fixture.project, self.fixture.project / 'nested', self.fixture.base,
                       self.fixture.root):
            args = self.fixture.options(output=output)
            with self.subTest(output=output), self.assertRaises(ValueError):
                validate_options(args, self.fixture.project, output)

    def test_cli_render_only_and_verify_from_are_mutually_exclusive(self) -> None:
        """The parser rejects ambiguity without calling the exporter."""
        arguments = ['native-short-export', str(self.fixture.project), str(self.fixture.base / 'next'),
                     '--render-only', '--verify-from', str(self.fixture.root / 'render-stage.json')]
        with mock.patch.object(sys, 'argv', arguments), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch('studio.native_short_export.execute') as execute, self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code, 2)
        execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()

"""Early audio failures avoid rendering; prepared float bytes retain final gates."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from audio import native_master_preparation as preparation
from audio.native_dialogue_delivery import NativeDialogueDelivery, _master
from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE, LEGACY_MASTERING_PROFILE
from audit.audit_checks import CheckResult, PASS, FAIL
from cut_preview_io import file_hash
from producer_config import MASTERING_POLICY_VERSION
from studio import native_short_worker as worker
from studio.native_short_delivery import prepare_dialogue
from _native_current_source_fixture import bind_test_motion_previews, write_test_json


class EarlyMasterTests(unittest.TestCase):
    """Real immutable fixture files; DSP is mocked in these contract tests."""

    def setUp(self) -> None:
        """Create private inert fixtures for policy checks without launching media tools."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.premaster = self.root / 'premaster.wav'
        self.premaster.write_bytes(b'TEST intended PCM')
        self.request = preparation.NativeMasterPreparation(self.premaster, file_hash(self.premaster),
            48000, self.root / 'early', NATIVE_SHORT_MASTERING_PROFILE)

    def make_master(self, request: preparation.NativeMasterPreparation, receipt: dict,
                    tools: tuple[str, str]) -> Path:
        """Simulate the shared master's exact outputs without claiming audio qualification."""
        master = request.directory / 'program-master.wav'
        master.write_bytes(b'TEST mastered PCM')
        receipt.update(premasterClock={}, masterClock={}, masteringFilter='TEST', masteringNote=None,
            masteringDecision={'TEST processing evidence': True},
            masteringPolicyVersion=MASTERING_POLICY_VERSION, masterDelivery={'qualified': True},
            masterSha256=file_hash(master))
        return master

    def prepare(self, status: str = PASS) -> tuple[Path, str]:
        """Drive real receipt persistence around synthetic audio checks."""
        with patch('audio.native_dialogue_delivery._master', side_effect=self.make_master), \
                patch.object(preparation, 'check_audio_program_quality',
                             return_value=[CheckResult('audio_tonal_hum', status, 'TEST', '')]):
            return preparation.prepare_native_master(self.request, ('ffmpeg', 'ffprobe'))

    def delivery(self, binding: tuple[Path, str]) -> NativeDialogueDelivery:
        """Bind actual fixture bytes for the downstream shared master dispatcher."""
        picture = self.root / 'picture.mp4'
        picture.write_bytes(b'TEST picture')
        directory = self.root / 'candidate'
        directory.mkdir()
        return NativeDialogueDelivery(picture, self.premaster, 48000, directory,
            file_hash(picture), file_hash(self.premaster), prepared_master=binding)

    def test_failed_early_hum_retains_failed_evidence(self) -> None:
        """Keep the failed precheck receipt without granting delivery or listening approval."""
        with self.assertRaisesRegex(RuntimeError, 'audio quality'):
            self.prepare(FAIL)
        record = json.loads((self.request.directory / 'receipt.json').read_text())
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['additionalAacEncodes'], 0)
        self.assertFalse(record['humanListeningApproved'])

    def test_prepared_master_is_copied_exactly_without_mastering_twice(self) -> None:
        """Reuse identical prepared float bytes without a second mastering pass."""
        request = self.delivery(self.prepare())
        with patch('audio.native_dialogue_delivery.render_float_master') as render, \
                patch('audio.program_audio_clock.exact_float_audio_clock', return_value={'samples': 48000}):
            receipt = {}
            result = _master(request, receipt, ('ffmpeg', 'ffprobe'))
        render.assert_not_called()
        self.assertEqual(result.read_bytes(), b'TEST mastered PCM')
        self.assertEqual(receipt['preparedMasterReceiptSha256'], request.prepared_master[1])
        self.assertEqual(receipt['masteringDecision'], {'TEST processing evidence': True})

    def test_changed_source_profile_sections_and_clock_fail_before_copy(self) -> None:
        """Reject changed source, profile, section mapping or sample count before reuse."""
        request = self.delivery(self.prepare())
        variants = (replace(request, samples=96000), replace(request, profile=LEGACY_MASTERING_PROFILE),
                    replace(request, review_sections=({'start': 0, 'end': 1},)))
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaisesRegex(RuntimeError, 'matching policy'):
                preparation.reuse_prepared_master(changed, {}, ('ffmpeg', 'ffprobe'))
        self.premaster.write_bytes(b'changed source')
        with self.assertRaisesRegex(RuntimeError, 'premaster changed'):
            preparation.reuse_prepared_master(request, {}, ('ffmpeg', 'ffprobe'))
        self.assertFalse((request.directory / 'program-master.wav').exists())

    def test_changed_receipt_and_master_are_rejected(self) -> None:
        """Require both the sealed preparation receipt and its exact master bytes."""
        binding = self.prepare()
        request = self.delivery(binding)
        master = self.request.directory / 'program-master.wav'
        master.write_bytes(b'changed master')
        with self.assertRaisesRegex(RuntimeError, 'master bytes changed'):
            preparation.reuse_prepared_master(request, {}, ('ffmpeg', 'ffprobe'))
        binding[0].write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'hash changed'):
            preparation.reuse_prepared_master(request, {}, ('ffmpeg', 'ffprobe'))

    def test_short_preparation_passes_automatic_master_binding_to_shared_reader(self) -> None:
        """A discovered master must actually reach the worker's no-repeat-DSP boundary."""
        binding = self.prepare()
        request = {'output': str(self.root / 'retry'), 'preparedMaster': str(binding[0]),
                   'pins': {str(binding[0]): binding[1]}, 'tools': {'ffmpeg': 'ffmpeg', 'ffprobe': 'ffprobe'}}
        canvas = {'frameRate': '25/1', 'totalFrames': 25, 'segments': []}
        with patch('studio.native_short_delivery.dialogue_premaster', return_value=self.premaster), \
                patch('studio.native_short_delivery.prepare_native_master', return_value=binding) as master:
            result = prepare_dialogue(request, canvas)
        self.assertEqual(master.call_args.args[0].prepared_master, binding)
        self.assertEqual(result['kind'], 'master')
        self.assertEqual(result['masterReceiptSha256'], binding[1])


class EarlyAudioOrderTests(unittest.TestCase):
    """Source failures must stop before the unchanged high-quality picture command."""

    def setUp(self) -> None:
        """Create private inert fixtures for policy checks without launching media tools."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        project, output = self.root / 'project', self.root / 'output'
        project.mkdir(); output.mkdir()
        self.plan = {'canvas': {'frameRate': '25/1', 'totalFrames': 25}}
        write_test_json(project / 'SHORT-PROJECT.json', self.plan)
        (project / 'index.html').write_text('<p>TEST inert source</p>')
        node = os.environ.get('SNIPER_NODE_PATH') or shutil.which('node')
        self.assertIsNotNone(node, 'Installed Node is required for the real review validator')
        self.request = {'output': str(output), 'project': str(project), 'pins': {},
            'tools': {'node': str(Path(node).resolve())},
            'runtime': str(self.root / 'runtime'), 'cache': str(self.root / 'cache')}
        bind_test_motion_previews(self.request)
        self.enterContext(patch.object(worker, 'preflight', return_value={'status': 'static-checks-pass'}))
        self.enterContext(patch('studio.native_stage_evidence.read_native_capture_receipt',
            return_value={'status': 'native-references-and-seek-states-pass'}))
        self.enterContext(patch('studio.native_picture_references.check_samples'))

    def test_failed_audio_prevents_picture_and_final_mux(self) -> None:
        """Stop on early audio failure before any expensive picture or final assembly."""
        with patch('studio.native_short_delivery.prepare_dialogue', side_effect=RuntimeError('hum')), \
                patch('subprocess.run', wraps=subprocess.run) as render, patch.object(worker, 'finish_dialogue') as finish, \
                self.assertRaisesRegex(RuntimeError, 'hum'):
            worker.render_media(self.request, self.plan)
        self.assertFalse(any('render' in call.args[0] for call in render.call_args_list))
        finish.assert_not_called()

    def test_missing_motion_review_blocks_audio_and_picture(self) -> None:
        """Structurally prepared previews never bypass the independent-review gate."""
        self.request.pop('previewReviews')
        with patch('studio.native_short_delivery.prepare_dialogue') as prepare, \
                patch('subprocess.run', wraps=subprocess.run) as render, \
                patch.object(worker, 'finish_dialogue') as finish, \
                self.assertRaisesRegex(ValueError, 'independent moving-preview reviews'):
            worker.render_media(self.request, self.plan)
        prepare.assert_not_called()
        render.assert_not_called()
        finish.assert_not_called()

    def test_same_prepared_audio_reaches_final_qualification_after_picture(self) -> None:
        """Retain the same prepared master and final gates around unchanged render quality."""
        order, prepared = [], {'TEST': 'prepared audio'}
        audio = {'audioReviewRequired': False, 'audioQuality': []}
        actual = subprocess.run
        def execute(command: list[str], **kwargs: object) -> object:
            """Run the real review validator; stub only the expensive picture command."""
            if 'render' not in command:
                return actual(command, **kwargs)
            order.append('picture')
            return subprocess.CompletedProcess(command, 0)
        with patch('studio.native_short_delivery.prepare_dialogue', side_effect=lambda *a: order.append('prepare') or prepared) as prepare, \
                patch('subprocess.run', side_effect=execute) as render, \
                patch.object(worker, 'finish_dialogue', side_effect=lambda *a: order.append('final-audio') or audio) as finish, \
                patch.object(worker, 'native_srgb_delivery', return_value={'output': 'TEST', 'sha256': 'TEST'}):
            worker.render_media(self.request, self.plan)
            from studio.native_motion_previews import prepare_audio
            self.assertEqual(prepare_audio(self.request, self.plan), prepared)
        prepare.assert_called_once()
        self.assertEqual(order, ['prepare', 'picture', 'final-audio'])
        self.assertEqual(finish.call_args.args[3], prepared)
        self.assertEqual(json.loads((Path(self.request['output']) / 'prepared-audio.json').read_text()), prepared)
        command = render.call_args.args[0]
        self.assertEqual(command[command.index('--quality') + 1], 'high')
        self.assertEqual(command[command.index('--crf') + 1], '15')
        self.assertIn('--no-best-effort', command)


if __name__ == '__main__':
    unittest.main()

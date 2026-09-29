"""Audio-input identity, supervised stage sealing, discovery and import (no DSP here)."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _budget_fixture import FakeClock, fake_clock
from _native_audio_stage_fixture import (AudioProjectFixture, FINISHING, canvas, copy_tree,
                                         fake_prepare_dialogue, owner_factory, write_json)
from audit.audit_checks import CheckResult, PASS
from cut_preview_io import file_hash
from studio import native_audio_seal as seal
from studio import native_audio_stage as stage
from studio.native_audio_contract import audio_input_contract, audio_input_identity
from studio.native_audio_import import bind_audio_stage
from studio.native_budget_clock import allocation, start_anchor
from studio.native_short_delivery import prepare_dialogue
from studio.native_short_export import select_and_publish


class AudioIdentityTests(unittest.TestCase):
    """Graphics never change the audio identity; every audio dependency does."""

    def setUp(self) -> None:
        """Build one TEST project and inert tool files."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.f = AudioProjectFixture(self.base)

    def identity(self, project: Path, profile: str = 'native-short-v1') -> str:
        """Hash the real contract for one project."""
        return audio_input_identity(audio_input_contract(project, profile, self.f.tools))

    def test_graphic_copy_font_edit_and_new_path_keep_identity(self) -> None:
        """A new project path with different title, views and extension markup reuses audio."""
        value = canvas()
        value.update(title='TEST revised title', pictureViews=[], captionViews=[{'startFrame': 0, 'endFrame': 150,
                     'box': [100, 1500, 880, 200]}])
        edited = self.f.write(self.base / 'native-v8', canvas=value, plan={'extension': {'markup': '<div>TEST</div>'},
                                                                       'catalogFiles': [{'file': 'compositions/t.html'}]})
        self.assertEqual(self.identity(self.f.project), self.identity(edited))
        copy_tree(self.f.project, self.base / 'moved')
        self.assertEqual(self.identity(self.f.project), self.identity(self.base / 'moved'))

    def test_cut_timing_finishing_profile_bytes_and_tools_change_identity(self) -> None:
        """Each audio-bearing change produces a different identity (a reuse miss)."""
        original = self.identity(self.f.project)
        variants = {
            'cut': self.f.write(self.base / 'cut', start=10.6),
            'timing': self.f.write(self.base / 'timing', frames=160),
            'cleanup': self.f.write(self.base / 'cleanup', plan={'audioFinishing': {**FINISHING,
                                                                  'audioEnhance': {'preset': 'voice'}}}),
            'gain': self.f.write(self.base / 'gain', plan={'audioFinishing': {**FINISHING, 'audioGain': [
                {'outStart': 1, 'outEnd': 2, 'dB': -3}]}}),
            'no-finishing': self.f.write(self.base / 'plain', plan={'audioFinishing': None}),
            'dialogue-bytes': self.f.write(self.base / 'bytes', dialogue=b'TEST other dialogue PCM')}
        seen = {original}
        for name, project in variants.items():
            with self.subTest(name=name):
                self.assertNotIn(self.identity(project), seen)
                seen.add(self.identity(project))
        self.assertNotEqual(self.identity(self.f.project, 'default-v3'), original)
        Path(self.f.tools['ffmpeg']).write_text('TEST different ffmpeg build')
        self.assertNotEqual(self.identity(self.f.project), original)

    def test_contract_names_clock_end_hold_mapping_and_no_paths(self) -> None:
        """The frozen contract carries exact clock/mapping fields and no project path."""
        value = canvas()
        value['segments'] = [{'startFrame': 0, 'endFrameExclusive': 140}]
        project = self.f.write(self.base / 'hold', canvas={**value, 'cuts': [{'start': 10.5, 'end': 10.5 + 140 / 30,
                                                                              'speed': 1}]})
        contract = audio_input_contract(project, 'native-short-v1', self.f.tools)
        self.assertEqual(contract['clock']['endHoldFrames'], 10)
        self.assertEqual(contract['clock']['totalSamples'], 240000)
        self.assertEqual(contract['offsets'], [[0, '1.000000000000']])
        self.assertEqual(contract['mappings'][0]['preparedFile'], 'assets/TEST-dialogue-0.wav')
        self.assertNotIn(str(self.base), json.dumps(contract))


class StageHarness(unittest.TestCase):
    """Run the real parent/worker/seal code with only DSP and supervision faked."""

    def setUp(self) -> None:
        """Create a project, a TEST runtime and patched process/DSP boundaries."""
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
        self.prepare = self.enterContext(patch('studio.native_short_delivery.prepare_dialogue',
                                               side_effect=fake_prepare_dialogue))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def run_stage(self, name: str = 'audio-v1', project: Path | None = None) -> dict:
        """Prepare and seal one stage through the public entry point."""
        plan = stage.AudioStagePlan(project or self.f.project, self.parent / name, runtime=self.runtime)
        return stage.prepare_stage(plan)


class AudioStageTests(StageHarness):
    """Sealing, failure, tamper, staleness and discovery behavior."""

    def test_stage_seals_premaster_master_receipts_and_closure(self) -> None:
        """A clean owner yields an immutable seal that the reader re-verifies."""
        record = self.run_stage()
        self.assertEqual(record['status'], seal.SEAL_STATUS)
        self.assertEqual(record['leaseClass'], 'audio')
        self.assertIn('scripts/producer/studio/native_audio_stage.py', record['implementation'])
        self.assertEqual(record['premaster']['sha256'], file_hash(self.parent / 'audio-v1/work/dialogue-cleanup/'
                                                                  'dialogue-finished.wav'))
        self.assertFalse(record['humanListeningApproved'])
        self.assertEqual(seal.read_sealed_stage(self.parent / 'audio-v1/audio-stage.json'), record)
        request = json.loads((self.parent / 'audio-v1/stage-request.json').read_text())
        self.assertEqual(request['workSeconds'] + request['capacityWaitSeconds'], 900)

    def test_owner_runs_in_the_audio_class_under_the_export_budget(self) -> None:
        """Inside an export the owner inherits its launch budget; standalone it is budgeted by folder."""
        seen, factory = [], owner_factory(stage.worker)
        with patch('studio.native_run.NativeRun',
                   side_effect=lambda label, settings: seen.append(settings) or factory(label, settings)), \
                fake_clock(FakeClock()):
            grant = allocation(start_anchor(), 700, 45)
            self.run_stage('standalone')
            for name, request in (('unbudgeted', {}), ('budgeted', {'productionBudget': {'allocation': grant}})):
                stage.prepare_stage(stage.AudioStagePlan(self.f.project, self.parent / name, runtime=self.runtime,
                                                         export_request=request))
        self.assertEqual([settings.lane for settings in seen], ['audio'] * 3)
        self.assertEqual([settings.serves for settings in seen[:2]], [None, ()])
        self.assertEqual((seen[2].hard_deadline, seen[2].deadline), (grant, 655))

    def test_failed_audio_quality_is_recorded_and_never_sealed_or_reused(self) -> None:
        """A bad finishing choice fails the stage with its reason and no reusable seal."""
        self.prepare.side_effect = RuntimeError('Early native float master failed shared audio quality checks')
        with self.assertRaises(stage.AudioStageFailure) as caught:
            self.run_stage()
        self.assertIn('failed shared audio quality checks', str(caught.exception))
        root = self.parent / 'audio-v1'
        self.assertFalse((root / seal.SEAL_NAME).exists())
        self.assertEqual(json.loads((root / seal.FAILED_NAME).read_text())['reusable'], False)
        identity = audio_input_identity(audio_input_contract(self.f.project, 'native-short-v1', self.f.tools))
        self.assertIsNone(seal.discover_stage(self.parent, identity))

    def test_tampered_master_or_inventory_is_rejected(self) -> None:
        """Every sealed byte and the exact artifact inventory are re-verified."""
        self.run_stage()
        root = self.parent / 'audio-v1'
        (root / 'work/extra.wav').write_bytes(b'TEST unexpected file')
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            seal.read_sealed_stage(root / seal.SEAL_NAME)
        (root / 'work/extra.wav').unlink()
        (root / 'work/audio-preparation/program-master.wav').write_bytes(b'TEST altered master')
        with self.assertRaisesRegex(ValueError, 'master changed'):
            seal.read_sealed_stage(root / seal.SEAL_NAME)

    def test_changed_code_makes_a_seal_stale_not_reusable(self) -> None:
        """Discovery skips a seal whose executed implementation changed; explicit use fails."""
        record = self.run_stage()
        with patch.object(seal, 'implementation_current', return_value=False):
            self.assertIsNone(seal.discover_stage(self.parent, record['audioInputSha256']))
            with self.assertRaises(seal.StaleAudioStage):
                seal.read_sealed_stage(self.parent / 'audio-v1' / seal.SEAL_NAME)

    def test_discovery_matches_identity_across_standalone_and_in_attempt_layouts(self) -> None:
        """Siblings are found by identity; another clip's audio is never selected."""
        other = self.f.write(self.base / 'other', start=10.6)
        first = self.run_stage('audio-v1')
        (self.parent / 'attempt-x').mkdir()
        self.run_stage('attempt-x/audio-stage', other)
        found, record = seal.discover_stage(self.parent, first['audioInputSha256'])
        self.assertEqual(found, self.parent / 'audio-v1' / seal.SEAL_NAME)
        other_identity = audio_input_identity(audio_input_contract(other, 'native-short-v1', self.f.tools))
        self.assertEqual(seal.discover_stage(self.parent, other_identity)[0],
                         self.parent / 'attempt-x/audio-stage' / seal.SEAL_NAME)
        self.assertNotEqual(record['audioInputSha256'], other_identity)


class AudioImportTests(StageHarness):
    """Exports bind stages by identity and import exact bytes without remastering."""

    def setUp(self) -> None:
        """Keep per-project attempt history private to this test."""
        super().setUp()
        self.enterContext(patch('studio.native_export_history.history_directory', return_value=self.base / 'history'))

    def request(self, name: str, project: Path | None = None) -> dict:
        """An unpublished export request for a new attempt beside the stage."""
        return {'project': str(project or self.f.project), 'output': str(self.parent / name),
                'runtime': str(self.runtime / 'hyperframes'), 'tools': self.f.tools,
                'audioProfile': 'native-short-v1', 'pins': {}}

    def test_a_cluttered_sibling_stage_is_skipped_not_fatal(self) -> None:
        """Discovery offers reuse only: an unverifiable sibling is not a match; an intact one is used."""
        self.run_stage('audio-v1')
        self.run_stage('audio-v2')
        (self.parent / 'audio-v2/work/.DS_Store').write_bytes(b'TEST Finder metadata')
        bound = bind_audio_stage(self.request('final-v2'), None)['audioStage']
        self.assertEqual((bound['mode'], Path(bound['seal']).parent.name), ('discovered', 'audio-v1'))
        with self.assertRaisesRegex(ValueError, 'inventory changed'):   # an explicit selection still fails closed
            bind_audio_stage(self.request('final-v3'), self.parent / 'audio-v2')

    def test_history_attempts_in_another_parent_are_discovered(self) -> None:
        """A same-identity stage inside an attempt listed by project history is found by content."""
        elsewhere = self.base / 'elsewhere'
        elsewhere.mkdir()
        (elsewhere / 'attempt-1').mkdir()
        plan = stage.AudioStagePlan(self.f.project, elsewhere / 'attempt-1/audio-stage', runtime=self.runtime)
        record = stage.prepare_stage(plan)
        self.assertIsNone(seal.discover_stage(self.parent, record['audioInputSha256']))
        found, _record = seal.discover_stage(self.parent, record['audioInputSha256'], (elsewhere / 'attempt-1',))
        self.assertEqual(found, plan.root / seal.SEAL_NAME)

    def test_binding_modes_and_refusals(self) -> None:
        """Absent → attempt stage; sealed sibling → discovered; recovered audio stays untouched."""
        attempt = bind_audio_stage(self.request('final-v1'), None)
        self.assertEqual(attempt['audioStage']['mode'], 'attempt')
        record = self.run_stage()
        found = bind_audio_stage(self.request('final-v2'), None)['audioStage']
        self.assertEqual((found['mode'], found['sealSha256']), ('discovered', file_hash(self.parent /
                         'audio-v1' / seal.SEAL_NAME)))
        self.assertEqual(found['audioInputSha256'], record['audioInputSha256'])
        donor = {**self.request('final-v3'), 'audioDonor': '/TEST/receipt.json'}
        self.assertNotIn('audioStage', bind_audio_stage(dict(donor), None))
        with self.assertRaisesRegex(ValueError, 'cannot replace'):
            bind_audio_stage(donor, self.parent / 'audio-v1')
        mismatch = self.f.write(self.base / 'retimed', start=10.6)
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            bind_audio_stage(self.request('final-v4', mismatch), self.parent / 'audio-v1')

    def test_published_export_request_carries_the_discovered_stage(self) -> None:
        """The public publication boundary binds the sealed stage before writing the request."""
        record = self.run_stage()
        request = {**self.request('preview-v1'), 'runtime': str(self.runtime / 'hyperframes'),
                   'captureMode': 'sdk-streaming', 'sourceCacheMode': 'acquire-sdk-preflight',
                   'audioDonor': None, 'pictureDonor': None, 'preparedMaster': None, 'cache': str(self.base / 'cache')}
        args = argparse.Namespace(audio_stage=None, resume_from=None, verify_from=None, audio_donor=None,
                                  picture_donor=None, preview_only=True, preview_reviews=None, preview_from=None)
        with patch('studio.native_short_export.hold_source_store_owner', return_value='/TEST/owner.lock'):
            published = select_and_publish(args, request, None)
        saved = json.loads((self.parent / 'preview-v1/export-request.json').read_text())
        self.assertEqual(saved['audioStage'], published['audioStage'])
        self.assertEqual(saved['audioStage']['audioInputSha256'], record['audioInputSha256'])
        self.assertEqual(saved['pins'][saved['audioStage']['seal']], saved['audioStage']['sealSha256'])

    def test_graphic_edit_import_copies_sealed_bytes_without_remastering(self) -> None:
        """A new project path imports the same premaster/master; no cleanup or mastering runs."""
        record = self.run_stage()
        edited = self.f.write(self.base / 'native-v8', plan={'extension': {'markup': '<div>TEST v8</div>'}})
        request = bind_audio_stage(self.request('final-v1', edited), None)
        (self.parent / 'final-v1').mkdir()
        checks = [CheckResult('audio_tonal_hum', PASS, 'TEST', '')]
        self.prepare.side_effect = None
        with patch('audio.native_master_preparation.check_audio_program_quality', return_value=checks), \
                patch('audio.program_audio_clock.exact_float_audio_clock', return_value={'TEST': True}), \
                patch('audio.native_dialogue_delivery.render_float_master') as master, \
                patch('studio.native_short_delivery.dialogue_premaster') as premaster:
            value = json.loads((edited / 'SHORT-PROJECT.json').read_text())['canvas']
            prepared = prepare_dialogue(request, value, FINISHING)
        master.assert_not_called()
        premaster.assert_not_called()
        self.assert_import(prepared, record)

    def assert_import(self, prepared: dict, record: dict) -> None:
        """The attempt's prepared audio points at in-attempt copies of the sealed bytes."""
        root = self.parent / 'final-v1'
        receipt = json.loads(Path(prepared['masterReceipt']).read_text())
        self.assertTrue(Path(prepared['reference']).is_relative_to(root))
        self.assertEqual(prepared['referenceSha256'], record['premaster']['sha256'])
        self.assertEqual(receipt['masterSha256'], record['master']['sha256'])
        self.assertEqual(receipt['preparedMasterReceiptSha256'], record['masterReceipt']['sha256'])
        self.assertEqual(file_hash(root / 'audio-preparation/program-master.wav'), record['master']['sha256'])
        self.assertEqual(prepared['audioStage']['masteringPassesRun'], 0)


if __name__ == '__main__':
    unittest.main()

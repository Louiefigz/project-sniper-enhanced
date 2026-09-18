"""Automatic Short recovery exercises real seals and discovery, with inert child execution."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _native_short_pipeline_fixture import ShortPipelineFixture, write_json
from studio.native_export_history import candidate_attempts, register_attempt, known_attempts
from studio.native_runtime import digest
from studio.native_short_autoresume import recover_automatically
from studio.native_short_export import execute, prepare, select_and_publish
from studio.native_short_pipeline import NativeShortPipeline


class AutomaticShortRecoveryTests(unittest.TestCase):
    """No flag is needed; exact current input and retained authority remain mandatory."""

    def setUp(self) -> None:
        """Keep fixture discovery and immutable history entirely within a private directory."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.f = ShortPipelineFixture(self.base)
        self.enterContext(patch('studio.native_export_history.history_directory', return_value=self.base / 'history'))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def completed(self) -> Path:
        """Publish a genuine shared stage seal around clearly synthetic media bytes."""
        seal = self.f.seal()
        self.f.terminal()
        return seal

    def test_normal_command_reuses_media_then_capture_across_repeated_retries(self) -> None:
        """Use the actual CLI execute path; only preflight/environment and children are stubs."""
        self.completed()
        options = self.f.options(cache=Path(self.f.request['cache']))
        with patch('studio.native_short_export.local_environment', return_value=(self.f.request['tools'], {})), \
                patch('studio.native_short_export.subprocess.run') as validator, \
                patch('studio.native_short_export.install_runtime', return_value=self.f.runtime), \
                patch('studio.native_short_export.input_pins', return_value=dict(self.f.inputs)), \
                patch('studio.native_short_pipeline.NativeRun', side_effect=self.f.owner_factory):
            self.assertTrue(execute(options))
            self.assertEqual([label for label, _ in self.f.calls], ['capture', 'verification'])
            other = self.base / 'elsewhere'; other.mkdir()
            options.output = other / 'retry'
            self.f.calls.clear()
            self.assertTrue(execute(options))
        self.assertEqual([label for label, _ in self.f.calls], ['verification'])
        self.assertEqual(validator.call_args.args[0][-2:], ['check-export', str(self.f.project)])
        result = json.loads((options.output / 'delivery.json').read_text())
        self.assertTrue(result['renderReused'])
        self.assertFalse(result['humanApproved'])
        self.assertEqual(digest(options.output / 'review.mp4'), digest(self.f.root / 'review.mp4'))

    def test_current_source_and_every_policy_change_start_fresh(self) -> None:
        """Automatic discovery must not silently inherit an old route or omit a new reference map."""
        self.completed()
        variants = [{'pins': {**self.f.inputs, str(self.f.source): 'a' * 64}},
                    {'captureMode': 'cached-native-batches'}, {'sourceCacheMode': 'acquire-sequential-sdr'},
                    {'audioProfile': 'changed'}, {'runtime': '/TEST/other'}, {'tools': {}},
                    {'cache': '/TEST/other'}, {'referenceMap': '/TEST/other.json'}]
        for change in variants:
            with self.subTest(change=change):
                result = recover_automatically({**self.f.current(), **change})
                self.assertEqual(result['recoverySelection']['mode'], 'fresh')
                self.assertNotIn('verifyStage', result)

    def test_active_attempt_blocks_even_when_an_older_completed_one_exists(self) -> None:
        """Do not duplicate work under a second attempt directory or reclaim an uncertain owner."""
        self.completed()
        active = self.base / 'active'; active.mkdir()
        self.f.write_request(self.f.current(active))
        with self.assertRaisesRegex(ValueError, 'active or interrupted'):
            recover_automatically(self.f.current())
        self.f.terminal('running', active)
        with self.assertRaisesRegex(ValueError, 'no terminal'):
            recover_automatically(self.f.current())

    def test_corrupt_selected_media_never_silently_rerenders(self) -> None:
        """A completed-looking but changed artifact is an evidence error, not a cache miss."""
        self.completed()
        (self.f.root / 'review.mp4').write_bytes(b'TEST changed completed artifact')
        with self.assertRaises((ValueError, RuntimeError)):
            recover_automatically(self.f.current())

    def test_recovery_preserves_extra_dependency_closure(self) -> None:
        """A stage originally rendered from reused evidence keeps that evidence on every retry."""
        current = self.f.current()
        evidence = self.base / 'TEST-earlier-owner.json'; evidence.write_text('TEST original evidence')
        self.f.inputs[str(evidence)] = digest(evidence)
        self.f.write_request(self.f.request)
        self.completed()
        result = recover_automatically(current)
        self.assertEqual(result['renderInputs'][str(evidence)], digest(evidence))
        evidence.write_text('TEST changed earlier proof')
        with self.assertRaises((ValueError, RuntimeError)):
            recover_automatically(current)

    def test_history_finds_other_parent_and_rejects_changed_request(self) -> None:
        """Pointers aid discovery but never replace original immutable requests."""
        self.completed()
        register_attempt(self.f.request)
        other = self.base / 'elsewhere'; other.mkdir()
        current = self.f.current(other / 'retry')
        self.assertEqual(recover_automatically(current)['recoverySelection']['attempt'], str(self.f.root))
        (self.f.root / 'export-request.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'history changed'):
            recover_automatically(current)

    def test_published_request_blocks_another_retry_before_worker_starts(self) -> None:
        """Discovery and registration finish inside reservation before returning to execution."""
        self.completed()
        request = select_and_publish(self.f.options(), self.f.current(), None)
        self.assertEqual(json.loads((Path(request['output']) / 'export-request.json').read_text()), request)
        self.assertEqual(known_attempts(request), [Path(request['output'])])
        with self.assertRaisesRegex(ValueError, 'active or interrupted'):
            select_and_publish(self.f.options(), self.f.current(self.base / 'third'), None)
        self.assertFalse((self.base / 'third').exists())

    def test_explicit_donor_remains_selected_without_automatic_override(self) -> None:
        """An explicit donor remains an explicit instruction, even with another active attempt."""
        donor = self.base / 'TEST-explicit-receipt.json'; donor.write_text('{}')
        with patch('studio.native_short_export.recover_automatically') as automatic:
            result = select_and_publish(self.f.options(audio_donor=donor), self.f.current(), None)
        automatic.assert_not_called()
        self.assertEqual(result['audioDonor'], str(donor))

    def test_partial_float_audio_uses_shared_master_without_claiming_picture(self) -> None:
        """A picture failure can keep its completed audio preparation independently."""
        receipt = self.f.partial_audio()
        result = recover_automatically(self.f.current())
        self.assertEqual(result['preparedMaster'], str(receipt))
        self.assertEqual(result['recoverySelection']['reused'], 'audio')
        self.assertIsNone(result['pictureDonor'])
        (receipt.parent / 'program-master.wav').write_bytes(b'TEST changed master')
        with self.assertRaisesRegex(ValueError, 'master changed'):
            recover_automatically(self.f.current())

    def test_failed_audio_or_unproven_picture_is_not_reused(self) -> None:
        """Incomplete files never acquire success authority merely by being on disk."""
        receipt = self.f.partial_audio()
        write_json(receipt, {'status': 'failed'})
        (self.f.root / 'picture.mp4').write_bytes(b'TEST unfinished picture')
        result = recover_automatically(self.f.current())
        self.assertEqual(result['recoverySelection']['mode'], 'fresh')

    def test_partial_owner_cleanup_and_identity_cannot_be_missing(self) -> None:
        """A qualified-looking master alone cannot authorize reuse from an unresolved worker."""
        self.f.partial_audio()
        file = self.f.root / 'pipeline.render.json'
        owner = json.loads(file.read_text())
        for changes in ({'cleanup': {'verified': False}}, {'ownerIdentities': []}, {'args': []},
                        {'receiptOwnershipFailed': True}, {'status': 'running'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                write_json(file, {**owner, **changes})
                recover_automatically(self.f.current())

    def test_picture_claim_delegates_to_qualified_donor_reader(self) -> None:
        """Selection cannot bypass SDK/batch proof checks or hide their rejection."""
        self.f.partial_audio()
        (self.f.root / 'audio').mkdir()
        write_json(self.f.root / 'audio/receipt.json', {'status': 'failed', 'picture': {'TEST': 'claimed'}})
        with patch('studio.native_short_autoresume.picture_reuse_pins', side_effect=ValueError('TEST bad picture')) as read:
            with self.assertRaisesRegex(ValueError, 'bad picture'):
                recover_automatically(self.f.current())
        read.assert_called_once_with(self.f.project, self.f.root)

    def test_qualified_aac_is_preferred_to_repeating_encoding(self) -> None:
        """Bind original receipt, float master and encoded candidate for shared AAC admission."""
        self.f.partial_audio()
        directory = self.f.root / 'audio'; directory.mkdir()
        master, candidate = directory / 'program-master.wav', directory / 'candidate.mp4'
        master.write_bytes(b'TEST finished master'); candidate.write_bytes(b'TEST AAC candidate')
        receipt = directory / 'receipt.json'
        write_json(receipt, {'status': 'audio-qualified', 'masterSha256': digest(master),
                             'candidateSha256': digest(candidate)})
        result = recover_automatically(self.f.current())
        self.assertEqual(result['audioDonor'], str(receipt))
        self.assertIsNone(result['preparedMaster'])
        self.assertTrue(all(str(file) in result['pins'] for file in (receipt, master, candidate)))
        candidate.write_bytes(b'TEST changed AAC')
        with self.assertRaisesRegex(ValueError, 'donor bytes changed'):
            recover_automatically(self.f.current())

    def test_discovery_is_bounded_and_skips_symlink_directories(self) -> None:
        """Do not recurse through arbitrary filesystems or scan unbounded histories."""
        alias = self.base / 'alias'; alias.symlink_to(self.f.root, target_is_directory=True)
        self.assertNotIn(alias, candidate_attempts(self.f.current()))
        with patch('studio.native_export_history.MAX_HISTORY', 1), self.assertRaisesRegex(ValueError, 'exceeds'):
            candidate_attempts(self.f.current())


if __name__ == '__main__':
    unittest.main()

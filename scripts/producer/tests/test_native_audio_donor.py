"""Actual donor profile/byte contracts with no codecs, DSP, browser or media jobs."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio import native_audio_donor as donor
from audio import native_dialogue_delivery as delivery
from audio.aac_peak_candidates import AAC_PEAK_CANDIDATE_POLICY, corrected_peak_profile
from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE, LEGACY_MASTERING_PROFILE
from audio.native_aac_encoding import native_aac_encoding_policy
from audio.native_master_preparation import NativeMasterPreparation
from audit.audit_checks import CheckResult, PASS, FAIL
from cut_preview_io import file_hash
from producer_config import MASTERING_POLICY_VERSION
from studio import native_short_delivery as short


class NativeAudioDonorTests(unittest.TestCase):
    """Early and final reuse admit the same actual master, including peak correction."""

    def setUp(self) -> None:
        """Create private inert fixtures for policy checks without launching media tools."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.premaster = self.root / 'premaster.wav'
        self.premaster.write_bytes(b'TEST exact intended float source')
        self.picture = self.root / 'picture.mp4'
        self.picture.write_bytes(b'TEST picture')
        self.prior_root = self.root / 'prior'
        self.prior_root.mkdir()
        self.master = self.prior_root / 'program-master.wav'
        self.master.write_bytes(b'TEST qualified corrected float master')
        self.candidate = self.prior_root / 'candidate.mp4'
        self.candidate.write_bytes(b'TEST qualified corrected AAC')
        self.profile = NATIVE_SHORT_MASTERING_PROFILE
        self.sections = ({'start': 0, 'end': 1, 'label': 'TEST current section'},)
        self.request = NativeMasterPreparation(self.premaster, file_hash(self.premaster), 48000,
            self.root / 'early', self.profile, self.sections)
        self.prior = self.prior_root / 'receipt.json'
        self.failure = {'qualified': False, 'audioDecodeSucceeded': True, 'audioDecodeExitCode': 0,
            'lufsWithinTolerance': True, 'truePeakWithinCeiling': False,
            'integratedLufs': -14.42, 'truePeakDbtp': -0.65}
        self.effective = corrected_peak_profile(self.profile, self.failure, 1)
        self.record = self.corrected_receipt()
        self.prior.write_text(json.dumps(self.record))

    def corrected_receipt(self) -> dict:
        """Use the actual correction algorithm and complete original candidate history."""
        common = {'inputPremasterSha256': self.request.premaster_sha256, 'aacEncodesCompleted': 1,
                  'aacEncodingPolicy': native_aac_encoding_policy(self.profile)}
        first = {**common, 'candidateIndex': 1, 'status': 'failed', 'delivery': self.failure,
                 'masteringProfile': self.profile.receipt()}
        second = {**common, 'candidateIndex': 2, 'status': 'audio-qualified',
            'masteringProfile': self.effective.receipt(), 'masterSha256': file_hash(self.master),
            'candidateSha256': file_hash(self.candidate)}
        return {**common, 'status': 'audio-qualified', 'masteringFilter': 'TEST actual donor chain',
            'masteringNote': None, 'masteringPolicyVersion': MASTERING_POLICY_VERSION,
            'requestedMasteringProfile': self.profile.receipt(), 'masteringProfile': self.effective.receipt(),
            'audioClock': {'presentedSamples': 48000}, 'masterSha256': file_hash(self.master),
            'candidateSha256': file_hash(self.candidate), 'encodingCandidateSha256': file_hash(self.candidate),
            'aacCandidateOrigin': 'current-run', 'aacCandidatePolicy': AAC_PEAK_CANDIDATE_POLICY,
            'aacCandidates': [first, second]}

    def prepare(self, status: str = PASS) -> tuple[Path, str]:
        """Check real fixture identities while only acoustic measurement is stubbed."""
        with patch.object(donor, 'exact_float_audio_clock', return_value={'samples': 48000}), \
                patch.object(donor, 'measure_delivery', return_value={'qualified': True}), \
                patch.object(donor, 'check_audio_program_quality',
                    return_value=[CheckResult('audio_tonal_hum', status, 'TEST', '')]) as check, \
                patch.object(delivery, '_master', side_effect=AssertionError('unused mastering')), \
                patch.object(delivery, '_encode', side_effect=AssertionError('unexpected encode')):
            binding = donor.prepare_audio_donor(self.request, self.prior, ('ffmpeg', 'ffprobe'))
        check.assert_called_once_with(str(self.master), {'audioReviewSections': list(self.sections)})
        return binding

    def test_corrected_profile_prechecks_actual_donor_without_master_or_encode(self) -> None:
        """Precheck the actual corrected donor while avoiding new mastering and AAC work."""
        binding = self.prepare()
        record = json.loads(binding[0].read_text())
        self.assertEqual(record['masteringProfile']['internalTruePeakDbtp'], -3.6)
        self.assertEqual(record['requestedMasteringProfile']['internalTruePeakDbtp'], -2.5)
        self.assertEqual(record['output'], str(self.master))
        self.assertEqual(record['additionalMasteringPasses'], 0)
        self.assertEqual(record['additionalAacEncodes'], 0)
        self.assertFalse((self.request.directory / 'program-master.wav').exists())

    def test_final_reuse_keeps_all_encoded_gates_after_same_early_donor(self) -> None:
        """Reuse admitted AAC packets while preserving current encoded qualification."""
        binding = self.prepare()
        output = self.root / 'final'
        output.mkdir()
        request = delivery.NativeDialogueDelivery(self.picture, self.premaster, 48000, output,
            file_hash(self.picture), file_hash(self.premaster), self.prior,
            review_sections=self.sections, prepared_donor=binding)
        picture = SimpleNamespace(path=str(self.picture), time_base=Fraction(1, 90000))
        with patch.object(delivery, '_master', side_effect=AssertionError('mastered')), \
                patch.object(delivery, 'exact_float_audio_clock', return_value={}), \
                patch.object(delivery, 'measure_delivery', return_value={'qualified': True}), \
                patch.object(delivery, 'observe_picture_source', return_value=picture), \
                patch.object(delivery, 'run_audio') as mux, \
                patch.object(delivery, 'packet_signature', return_value='TEST same AAC'), \
                patch.object(delivery, '_qualify') as qualify:
            result = {}
            delivery._reuse(request, result, ('ffmpeg', 'ffprobe'))
        self.assertEqual((output / 'program-master.wav').read_bytes(), self.master.read_bytes())
        self.assertEqual(result['preparedDonorReceiptSha256'], binding[1])
        self.assertEqual(result['masteringProfile'], self.effective.receipt())
        self.assertEqual(mux.call_args.args[0][mux.call_args.args[0].index('-c') + 1], 'copy')
        qualify.assert_called_once()
        self.assertTrue(result['aacPacketsReused'])

    def test_failed_early_check_preserves_failed_evidence(self) -> None:
        """Preserve failed donor evidence without implying completed preparation."""
        with self.assertRaisesRegex(RuntimeError, 'audio quality'):
            self.prepare(FAIL)
        record = json.loads((self.request.directory / 'receipt.json').read_text())
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['additionalMasteringPasses'], 0)

    def test_source_profile_clock_and_corrected_history_are_not_reinterpreted(self) -> None:
        """Reject changed clocks, profiles and fabricated peak-correction history."""
        for request in (replace(self.request, samples=96000), replace(self.request, profile=LEGACY_MASTERING_PROFILE)):
            with self.subTest(request=request), self.assertRaises(RuntimeError):
                donor.admit_audio_donor(self.prior, (request.premaster, request.premaster_sha256),
                                        request.samples, request.profile)
        self.record['aacCandidates'][0]['aacEncodingPolicy'] = {}
        self.prior.write_text(json.dumps(self.record))
        with self.assertRaisesRegex(RuntimeError, 'AAC encoding policy'):
            donor.admit_audio_donor(self.prior, (self.premaster, self.request.premaster_sha256), 48000, self.profile)

    def test_replaced_receipt_master_candidate_and_symlink_fail(self) -> None:
        """Reject changed donor artifacts and linked authority before reuse."""
        for file in (self.prior, self.master, self.candidate):
            original = file.read_bytes()
            file.write_bytes(b'TEST changed artifact')
            with self.subTest(file=file), self.assertRaises((ValueError, RuntimeError)):
                donor.admit_audio_donor(self.prior, (self.premaster, self.request.premaster_sha256), 48000, self.profile)
            file.write_bytes(original)
        self.master.unlink()
        self.master.symlink_to(self.premaster)
        with self.assertRaises((OSError, RuntimeError)):
            donor.admit_audio_donor(self.prior, (self.premaster, self.request.premaster_sha256), 48000, self.profile)

    def test_prepared_review_sections_must_match_actual_final_request(self) -> None:
        """Require the prepared review sections to match the current delivery request."""
        binding = self.prepare()
        request = delivery.NativeDialogueDelivery(self.picture, self.premaster, 48000, self.root / 'final',
            file_hash(self.picture), file_hash(self.premaster), self.prior, prepared_donor=binding)
        admitted = donor.admit_audio_donor(self.prior, (self.premaster, self.request.premaster_sha256), 48000, self.profile)
        with self.assertRaisesRegex(RuntimeError, 'Prepared audio donor differs'):
            donor.verify_prepared_donor(request, admitted)

    def test_native_short_selects_donor_preparation_and_passes_its_binding(self) -> None:
        """Carry the donor preparation binding through the Short delivery adapter."""
        binding = self.prepare()
        canvas = {'frameRate': '25/1', 'totalFrames': 25, 'segments': []}
        request = {'output': str(self.root), 'audioDonor': str(self.prior),
                   'tools': {'ffmpeg': 'ffmpeg', 'ffprobe': 'ffprobe'}}
        with patch.object(short, 'dialogue_premaster', return_value=self.premaster), \
                patch.object(short, 'prepare_native_master', side_effect=AssertionError('unused new master')), \
                patch.object(short, 'prepare_audio_donor', return_value=binding) as prepare:
            prepared = short.prepare_dialogue(request, canvas)
        prepare.assert_called_once()
        with patch.object(short, 'finish_native_dialogue') as finish:
            short.finish_dialogue(request, canvas, prepared=prepared)
        final = finish.call_args.args[0]
        self.assertIsNone(final.prepared_master)
        self.assertEqual(final.prepared_donor, binding)
        self.assertEqual(final.prior_receipt, self.prior)


if __name__ == '__main__':
    unittest.main()

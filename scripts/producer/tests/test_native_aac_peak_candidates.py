"""Bounded codec correction, lossless-source lineage and reuse without media jobs."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from audio import native_dialogue_delivery as delivery
from audio.aac_peak_candidates import (AAC_PEAK_CANDIDATE_POLICY, corrected_peak_profile,
                                      effective_reuse_profile)
from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE
from audio.native_aac_encoding import native_aac_encoding_policy
from fingerprints import file_sha256


def evidence(peak: float = -0.65, integrated: float = -14.42) -> dict:
    """Retain the actual failure's measurements with independently derived gate booleans."""
    return {"integratedLufs": integrated, "truePeakDbtp": peak,
        "audioDecodeSucceeded": True, "audioDecodeExitCode": 0,
        "lufsWithinTolerance": abs(integrated + 14) <= 1,
        "truePeakWithinCeiling": peak <= -1.5,
        "qualified": abs(integrated + 14) <= 1 and peak <= -1.5}


class NativeAacPeakCandidatesTests(unittest.TestCase):
    """The wrapper can retry peak-only errors; clocks, signal, inputs and gates stay strict."""

    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        picture, premaster = self.root / "picture.mp4", self.root / "original.wav"
        picture.write_bytes(b"picture"); premaster.write_bytes(b"original lossless source")
        self.request = delivery.NativeDialogueDelivery(picture, premaster, 1854720, self.root / "audio",
            file_sha256(str(picture)), file_sha256(str(premaster)))
        self.master_sources = []
        self.failures = 1
        self.failure_kind = "peak"

    def master(self, request: delivery.NativeDialogueDelivery, receipt: dict, _tools: tuple) -> Path:
        """Materialize distinct tiny float stand-ins while recording the requested real source."""
        self.master_sources.append((request.premaster, request.profile))
        output = request.directory / "program-master.wav"
        output.write_text(str(request.profile.internal_true_peak_dbtp))
        receipt.update(masterSha256=file_sha256(str(output)), masteringFilter="shared DSP",
            masteringNote=None, masteringPolicyVersion=3, masterDelivery=evidence(-3.6, -14.1))
        return output

    def encode(self, *args: object) -> Path:
        """Simulate complete encoding followed by the existing delivery gate's exact failure type."""
        request, _master, receipt, _tools = args
        output = request.directory / "candidate.mp4"
        output.write_text("AAC from " + str(request.profile.internal_true_peak_dbtp))
        failed = len(self.master_sources) <= self.failures
        measured = evidence() if failed else evidence(-1.85, -14.6)
        if self.failure_kind == "loudness":
            measured = evidence(-0.65, -16)
        receipt.update(aacEncodeInvocations=1, aacEncodesCompleted=1,
            aacEncodingPolicy=native_aac_encoding_policy(request.profile),
            candidateSha256=file_sha256(str(output)), delivery=measured, signal={"passed": True},
            audioClock={"presentedSamples": request.samples})
        if failed:
            error = delivery.NativeAacDeliveryError if self.failure_kind != "clock" else RuntimeError
            raise error("TEST encoded gate failure")
        return output

    def finish(self) -> dict:
        """Run the real bounded wrapper with only codec/DSP operations mocked."""
        with patch.object(delivery.shutil, "which", return_value="TEST tool"), \
                patch.object(delivery, "_master", side_effect=self.master), \
                patch.object(delivery, "_encode", side_effect=self.encode):
            return delivery.finish_native_dialogue(self.request)

    def test_observed_codec_excess_selects_stricter_shared_profile_without_global_changes(self) -> None:
        before = NATIVE_SHORT_MASTERING_PROFILE.receipt()
        effective = corrected_peak_profile(NATIVE_SHORT_MASTERING_PROFILE, evidence(), 1)
        self.assertEqual(effective.internal_true_peak_dbtp, -3.6)
        self.assertEqual(effective.audio_bitrate, "320k")
        self.assertEqual(effective.maximum_static_dry_runs, 6)
        self.assertEqual(NATIVE_SHORT_MASTERING_PROFILE.receipt(), before)

    def test_two_independent_lossless_candidates_retain_failed_bytes_and_promote_only_qualified_bytes(self) -> None:
        result = self.finish()
        self.assertEqual([row[1].internal_true_peak_dbtp for row in self.master_sources], [-2.5, -3.6])
        self.assertTrue(all(row[0] == self.request.premaster for row in self.master_sources))
        self.assertEqual(result["additionalAacEncodes"], 2)
        self.assertEqual(result["totalAacEncodeInvocations"], 2)
        self.assertEqual(result["audiblePathAacEncodes"], 1)
        self.assertEqual(result["requestedMasteringProfile"], NATIVE_SHORT_MASTERING_PROFILE.receipt())
        self.assertEqual(result["masteringProfile"]["internalTruePeakDbtp"], -3.6)
        self.assertEqual(effective_reuse_profile(result, self.request.profile).internal_true_peak_dbtp, -3.6)
        root = self.request.directory
        self.assertNotEqual((root / "attempt-01/candidate.mp4").read_bytes(), (root / "candidate.mp4").read_bytes())
        self.assertEqual((root / "attempt-02/candidate.mp4").read_bytes(), (root / "candidate.mp4").read_bytes())
        self.assertEqual(json.loads((root / "attempt-01/receipt.json").read_text())["status"], "failed")

    def test_first_pass_success_does_not_add_a_candidate(self) -> None:
        self.failures = 0
        result = self.finish()
        self.assertEqual(len(result["aacCandidates"]), 1)
        self.assertEqual(result["additionalAacEncodes"], 1)

    def test_three_failed_candidates_stop_without_promoting_any_output(self) -> None:
        self.failures = 10
        with self.assertLogs("audio.native_dialogue_delivery", level="ERROR"), self.assertRaisesRegex(RuntimeError, "budget"):
            self.finish()
        result = json.loads((self.request.directory / "receipt.json").read_text())
        self.assertEqual(len(self.master_sources), 3)
        self.assertEqual(result["additionalAacEncodes"], 3)
        self.assertFalse((self.request.directory / "candidate.mp4").exists())
        self.assertTrue(all((self.request.directory / f"attempt-{i:02d}/candidate.mp4").exists() for i in range(1, 4)))

    def test_clock_or_loudness_failure_cannot_trigger_peak_correction(self) -> None:
        for index, kind in enumerate(("clock", "loudness")):
            self.request = replace(self.request, directory=self.root / f"failure-{index}")
            self.master_sources = []; self.failure_kind = kind
            with self.assertLogs("audio.native_dialogue_delivery", level="ERROR"), self.assertRaises(RuntimeError):
                self.finish()
            self.assertEqual(len(self.master_sources), 1)

    def test_correction_rejects_nonfinite_or_contradictory_evidence_and_bounds(self) -> None:
        for update in ({"truePeakDbtp": float("nan")}, {"integratedLufs": True},
                       {"audioDecodeSucceeded": False}, {"qualified": True},
                       {"truePeakWithinCeiling": True}, {"truePeakDbtp": -4}, {"integratedLufs": -18}):
            with self.subTest(update=update), self.assertRaises(RuntimeError):
                corrected_peak_profile(self.request.profile, {**evidence(), **update}, 1)
        with self.assertRaisesRegex(RuntimeError, "headroom"):
            corrected_peak_profile(replace(self.request.profile, internal_true_peak_dbtp=-8.9), evidence(), 1)

    def test_effective_reuse_rejects_changed_settings_or_unproved_candidate_history(self) -> None:
        result = self.finish()
        mutations = (("masteringProfile", {**result["masteringProfile"], "audioBitrate": "256k"}),
                     ("requestedMasteringProfile", result["masteringProfile"]),
                     ("aacCandidatePolicy", {**AAC_PEAK_CANDIDATE_POLICY, "maximumCandidates": 4}),
                     ("encodingCandidateSha256", "0" * 64))
        for key, value in mutations:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                effective_reuse_profile({**result, key: value}, self.request.profile)
        changed = copy.deepcopy(result)
        changed["aacCandidates"][0]["delivery"] = evidence(-0.65, -18)
        with self.assertRaises(RuntimeError):
            effective_reuse_profile(changed, self.request.profile)
        reused = {**result, "aacCandidateOrigin": "reused-qualified-audio", "aacPacketsReused": True,
                  "candidateSha256": "1" * 64}
        self.assertEqual(effective_reuse_profile(reused, self.request.profile).internal_true_peak_dbtp, -3.6)

    def test_input_changes_do_not_consume_another_candidate(self) -> None:
        original = self.encode
        def mutate(request: delivery.NativeDialogueDelivery, master: Path, record: dict, tools: tuple) -> Path:
            self.request.premaster.write_bytes(b"changed source")
            return original(request, master, record, tools)
        with patch.object(delivery.shutil, "which", return_value="TEST tool"), \
                patch.object(delivery, "_master", side_effect=self.master), \
                patch.object(delivery, "_encode", side_effect=mutate), \
                self.assertLogs("audio.native_dialogue_delivery", level="ERROR"), \
                self.assertRaisesRegex(RuntimeError, "input bytes changed"):
            delivery.finish_native_dialogue(self.request)
        self.assertEqual(len(self.master_sources), 1)

    def test_master_mutation_cannot_be_reclassified_as_a_retryable_peak_failure(self) -> None:
        self.request.directory.mkdir()
        master = self.request.directory / 'program-master.wav'
        master.write_bytes(b'original master')
        (self.request.directory / 'candidate.mp4').write_bytes(b'encoded candidate')
        record = {'masterSha256': file_sha256(str(master))}
        def changed(_path: str) -> dict:
            master.write_bytes(b'changed during measurement')
            return evidence()
        with patch.object(delivery, 'observe_picture_source', return_value=object()), \
                patch.object(delivery, 'verify_picture_copy', return_value={}), \
                patch.object(delivery, 'exact_aac_audio_clock', return_value={}), \
                patch.object(delivery, 'verify_float_delivery_signal', return_value={'passed': True}), \
                patch.object(delivery, 'measure_delivery', side_effect=changed), \
                self.assertRaisesRegex(RuntimeError, 'changed during qualification') as failure:
            delivery._qualify(self.request, master, record, ('TEST ffmpeg', 'TEST ffprobe'))
        self.assertNotIsInstance(failure.exception, delivery.NativeAacDeliveryError)


if __name__ == "__main__":
    unittest.main()

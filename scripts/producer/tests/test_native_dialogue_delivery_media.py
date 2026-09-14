"""Real-codec coverage for shared native dialogue finishing and retained failures."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from audit.audit_checks import CheckResult, FAIL

from audio.native_dialogue_delivery import NativeDialogueDelivery, finish_native_dialogue
from audio.mastering_profile import LEGACY_MASTERING_PROFILE
from audio.render_audio_authority import run_audio
from fingerprints import file_sha256


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class NativeDialogueDeliveryMediaTests(unittest.TestCase):
    """Keep picture identity, exact audio clocks and local fidelity independently proved."""

    def setUp(self) -> None:
        """Create a small real picture and known float audio without model calls."""
        scratch = tempfile.TemporaryDirectory(prefix="native-dialogue-media-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        picture, premaster = self.root / "picture.mp4", self.root / "premaster.wav"
        run_audio(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
            "testsrc2=size=64x64:rate=25:duration=4", "-an", "-c:v", "libx264",
            "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(picture)])
        run_audio(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=4", "-ac", "2",
            "-c:a", "pcm_f32le", str(premaster)])
        self.request = NativeDialogueDelivery(picture, premaster, 192000, self.root / "result",
            file_sha256(str(picture)), file_sha256(str(premaster)))

    def test_real_finish_preserves_picture_and_qualifies_actual_encoded_audio(self) -> None:
        """The actual FFmpeg master and AAC decode must satisfy all shared gates."""
        result = finish_native_dialogue(self.request)
        self.assertEqual(result["status"], "audio-qualified")
        self.assertTrue(result["picture"]["picturePacketsIdentical"])
        self.assertEqual(result["picture"]["picturePackets"], 100)
        self.assertEqual(result["audioClock"]["presentedSamples"], 192000)
        self.assertTrue(result["signal"]["passed"])
        self.assertTrue(result["delivery"]["qualified"])
        self.assertFalse(result["humanListeningApproved"])
        self.assertFalse(result["approved"])
        with self.assertRaises(FileExistsError):
            finish_native_dialogue(self.request)
        self.assertEqual(file_sha256(result["output"]), result["candidateSha256"])

    def test_changed_source_is_retained_as_failure_before_any_encoding(self) -> None:
        """A path cannot substitute different bytes for the admitted premaster."""
        request = replace(self.request, premaster_sha256="0" * 64)
        with self.assertLogs("audio.native_dialogue_delivery", level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "input bytes changed"):
                finish_native_dialogue(request)
        receipt = json.loads((request.directory / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse((request.directory / "candidate.mp4").exists())

    def test_visual_revision_reuses_encoded_audio_with_all_delivery_gates(self) -> None:
        """A new picture can retain exactly the earlier qualified AAC packets."""
        first = finish_native_dialogue(self.request)
        request = replace(self.request, directory=self.root / "revision",
                          prior_receipt=self.request.directory / "receipt.json")
        result = finish_native_dialogue(request)
        self.assertEqual(result["additionalAacEncodes"], 0)
        self.assertTrue(result["aacPacketsReused"])
        self.assertTrue(result["signal"]["passed"])
        self.assertEqual(result["masterSha256"], first["masterSha256"])
        prior = json.loads(request.prior_receipt.read_text())
        prior["inputPremasterSha256"] = "0" * 64
        request.prior_receipt.write_text(json.dumps(prior))
        with self.assertLogs("audio.native_dialogue_delivery", level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "unchanged input|effective candidate profile"):
                finish_native_dialogue(replace(request, directory=self.root / "rejected"))

    def test_wrong_sample_contract_does_not_retime_or_pad_to_pass(self) -> None:
        """An incorrect requested clock is a failure rather than a repair hint."""
        request = replace(self.request, samples=self.request.samples - 1)
        with self.assertLogs("audio.native_dialogue_delivery", level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "exact sample count differs"):
                finish_native_dialogue(request)
        receipt = json.loads((request.directory / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse((request.directory / "program-master.wav").exists())

    def test_actual_legacy_donor_requires_explicit_default_profile(self) -> None:
        """Historical 256k AAC remains usable only when the caller selects its original profile."""
        legacy = replace(self.request, profile=LEGACY_MASTERING_PROFILE)
        first = finish_native_dialogue(legacy)
        prior_path = legacy.directory / "receipt.json"
        prior = json.loads(prior_path.read_text())
        prior.pop("masteringProfile")  # Reproduce an actual historical policy-3 receipt.
        for key in ("aacCandidatePolicy", "aacCandidates", "encodingCandidateSha256", "aacCandidateOrigin"):
            prior.pop(key, None)  # Historical receipts also predate candidate-profile binding.
        prior_path.write_text(json.dumps(prior))
        new_default = replace(self.request, directory=self.root / "new-profile", prior_receipt=prior_path)
        with self.assertLogs("audio.native_dialogue_delivery", level="ERROR"), \
                self.assertRaisesRegex(RuntimeError, "mastering profile"):
            finish_native_dialogue(new_default)
        self.assertFalse((new_default.directory / "candidate.mp4").exists())
        requested = replace(legacy, directory=self.root / "explicit-legacy", prior_receipt=prior_path)
        result = finish_native_dialogue(requested)
        self.assertEqual(result["masteringProfile"], LEGACY_MASTERING_PROFILE.receipt())
        self.assertEqual(result["masterSha256"], first["masterSha256"])
        self.assertEqual(result["additionalAacEncodes"], 0)
        self.assertTrue(result["aacPacketsReused"])
        self.assertTrue(result["signal"]["passed"])

    def test_malformed_reuse_receipt_is_retained_as_failure(self) -> None:
        """An invalid saved receipt must fail explicitly before copying or encoding."""
        prior = self.root / "prior.json"
        prior.write_text("[]")
        request = replace(self.request, prior_receipt=prior)
        with self.assertLogs("audio.native_dialogue_delivery", level="ERROR"), \
                self.assertRaisesRegex(ValueError, "incomplete or malformed"):
            finish_native_dialogue(request)
        receipt = json.loads((request.directory / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse((request.directory / "candidate.mp4").exists())

    def test_current_quality_failure_blocks_fresh_and_previously_qualified_donor(self) -> None:
        """A donor's old pass cannot replace a current channel/interval assessment."""
        first = finish_native_dialogue(self.request)
        self.assertTrue(first['audioQuality'])
        self.assertFalse(any(row['status'] == FAIL for row in first['audioQuality']))
        failure = [CheckResult('audio_channel_interval_000000', FAIL, '0.0-0.1s', 'test fault')]
        for name, donor in [('fresh', None), ('reuse', self.request.directory / 'receipt.json')]:
            request = replace(self.request, directory=self.root / name, prior_receipt=donor)
            with patch('audio.native_dialogue_delivery.check_audio_quality', return_value=failure) as quality, \
                    self.assertLogs('audio.native_dialogue_delivery', level='ERROR'), \
                    self.assertRaisesRegex(RuntimeError, 'shared audio quality'):
                finish_native_dialogue(request)
            quality.assert_called_once()
            receipt = json.loads((request.directory / 'receipt.json').read_text())
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(receipt['audioQuality'][0]['status'], FAIL)
            self.assertFalse(receipt['humanListeningApproved'])


if __name__ == "__main__":
    unittest.main()

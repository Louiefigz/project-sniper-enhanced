"""Native profile provenance, encoded bitrate and failure retention without media jobs."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio import native_dialogue_delivery as delivery
from audio.mastering_profile import LEGACY_MASTERING_PROFILE, NATIVE_SHORT_MASTERING_PROFILE
from audio.native_aac_encoding import native_aac_encoding_policy
from fingerprints import file_sha256


class NativeDialogueProfileTests(unittest.TestCase):
    """A prior file can be reused only under the settings that actually produced it."""

    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        picture, premaster = self.root / "picture.mp4", self.root / "premaster.wav"
        picture.write_bytes(b"picture fixture")
        premaster.write_bytes(b"float fixture")
        self.request = delivery.NativeDialogueDelivery(picture, premaster, 522240, self.root / "result",
            file_sha256(str(picture)), file_sha256(str(premaster)))

    def prior(self, profile: dict | None) -> Path:
        """Bind tiny non-media donor files; codec operations remain mocked in these unit tests."""
        directory = self.root / "prior"
        directory.mkdir(exist_ok=True)
        master, donor = directory / "program-master.wav", directory / "candidate.mp4"
        master.write_bytes(b"master fixture")
        donor.write_bytes(b"aac fixture")
        record = {"status": "audio-qualified", "masteringFilter": "prior chain", "masteringNote": None,
            "masteringPolicyVersion": 3, "masterSha256": file_sha256(str(master)),
            "candidateSha256": file_sha256(str(donor)), "inputPremasterSha256": self.request.premaster_sha256,
            "audioClock": {"presentedSamples": self.request.samples},
            "aacEncodingPolicy": native_aac_encoding_policy(
                LEGACY_MASTERING_PROFILE if profile is None else NATIVE_SHORT_MASTERING_PROFILE)}
        if profile is not None:
            record["masteringProfile"] = profile
        path = directory / "receipt.json"
        path.write_text(json.dumps(record))
        return path

    def test_new_native_request_uses_320k_and_passes_same_profile_to_shared_master(self) -> None:
        self.assertIs(self.request.profile, NATIVE_SHORT_MASTERING_PROFILE)
        master = self.root / "master.wav"
        master.write_bytes(b"float fixture")
        with patch.object(delivery, "exact_float_audio_clock", return_value={}), \
                patch.object(delivery, "_observe_final_audio", return_value=({}, 0, "")), \
                patch.object(delivery, "render_float_master", return_value=(master, "chain", None)) as render, \
                patch.object(delivery, "measure_delivery", return_value={"qualified": True}):
            delivery._master(self.request, {}, ("ffmpeg", "ffprobe"))
        self.assertIs(render.call_args.args[0].profile, NATIVE_SHORT_MASTERING_PROFILE)
        picture = SimpleNamespace(path=str(self.request.picture), time_base=Fraction(1, 90000))
        with patch.object(delivery, "observe_picture_source", return_value=picture), \
                patch.object(delivery, "run_audio") as run, patch.object(delivery, "_qualify") as qualify:
            delivery._encode(self.request, master, {}, ("ffmpeg", "ffprobe"))
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-b:a") + 1], "320k")
        self.assertEqual(command[command.index("-c:v") + 1], "copy")
        self.assertEqual(command[command.index("-ac") + 1], "2")
        qualify.assert_called_once()

    def test_reuse_rejects_missing_or_mismatched_profile_before_copy_or_media(self) -> None:
        mismatches = (None, LEGACY_MASTERING_PROFILE.receipt(),
            {**NATIVE_SHORT_MASTERING_PROFILE.receipt(), "audioBitrate": "256k"},
            {**NATIVE_SHORT_MASTERING_PROFILE.receipt(), "maximumStaticDryRuns": 2}, {})
        for profile in mismatches:
            with self.subTest(profile=profile):
                request = replace(self.request, prior_receipt=self.prior(profile))
                with patch.object(delivery.shutil, "copyfile") as copy, \
                        patch.object(delivery, "run_audio") as run, \
                        self.assertRaisesRegex(RuntimeError, "mastering profile"):
                    delivery._reuse(request, {}, ("ffmpeg", "ffprobe"))
                copy.assert_not_called()
                run.assert_not_called()

    def test_exact_profiles_with_explicit_encoder_policy_reuse_still_apply_shared_gates(self) -> None:
        for profile, prior_profile in ((NATIVE_SHORT_MASTERING_PROFILE, NATIVE_SHORT_MASTERING_PROFILE.receipt()),
                                       (LEGACY_MASTERING_PROFILE, None)):
            request = replace(self.request, profile=profile, prior_receipt=self.prior(prior_profile))
            request.directory.mkdir(exist_ok=True)
            picture = SimpleNamespace(path=str(request.picture), time_base=Fraction(1, 90000))
            with patch.object(delivery, "exact_float_audio_clock", return_value={}), \
                    patch.object(delivery, "measure_delivery", return_value={"qualified": True}), \
                    patch.object(delivery, "observe_picture_source", return_value=picture), \
                    patch.object(delivery, "run_audio"), patch.object(delivery, "packet_signature", return_value="same"), \
                    patch.object(delivery, "_qualify") as qualify:
                record = {}
                delivery._reuse(request, record, ("ffmpeg", "ffprobe"))
            qualify.assert_called_once()
            self.assertTrue(record["aacPacketsReused"])
            self.assertEqual(record["additionalAacEncodes"], 0)
            self.assertEqual(record["aacEncodingPolicy"], native_aac_encoding_policy(profile))

    def test_failed_processing_retains_selected_profile_for_all_supported_error_families(self) -> None:
        errors = (RuntimeError("gate"), ValueError("clock"), OSError("file"), subprocess.TimeoutExpired("ffmpeg", 1))
        for index, error in enumerate(errors):
            request = replace(self.request, directory=self.root / f"failed-{index}")
            with patch.object(delivery.shutil, "which", return_value="tool"), \
                    patch.object(delivery, "_master", side_effect=error), \
                    self.assertLogs("audio.native_dialogue_delivery", level="ERROR"), self.assertRaises(type(error)):
                delivery.finish_native_dialogue(request)
            record = json.loads((request.directory / "receipt.json").read_text())
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["masteringProfile"], NATIVE_SHORT_MASTERING_PROFILE.receipt())
            before = (request.directory / "receipt.json").read_bytes()
            with self.assertRaises(FileExistsError):
                delivery.finish_native_dialogue(request)
            self.assertEqual((request.directory / "receipt.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

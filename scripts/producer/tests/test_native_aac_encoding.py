"""Explicit native encoder options and donor rejection without media execution."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio import native_dialogue_delivery as delivery
from audio.mastering_profile import LEGACY_MASTERING_PROFILE, NATIVE_SHORT_MASTERING_PROFILE
from audio.native_aac_encoding import (native_aac_arguments, native_aac_encoding_policy,
                                       require_native_aac_policy)
from fingerprints import file_sha256
from producer_config import AUDIO, ENCODE


class NativeAacEncodingTests(unittest.TestCase):
    """Codec tools are explicit; lossless samples, gates and failure behavior stay owned."""

    def setUp(self) -> None:
        """Create small stand-ins; every codec and measurement call is mocked."""
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        picture, premaster = self.root / "picture.mp4", self.root / "premaster.wav"
        picture.write_bytes(b"picture fixture")
        premaster.write_bytes(b"lossless fixture")
        self.request = delivery.NativeDialogueDelivery(picture, premaster, 1176960, self.root / "audio",
            file_sha256(str(picture)), file_sha256(str(premaster)))
        self.picture = SimpleNamespace(path=str(picture), time_base=Fraction(1, 90000))

    def prior(self, policy: object) -> Path:
        """Keep master authority complete so rejection specifically tests encoder policy."""
        record = {"status": "audio-qualified", "masteringFilter": "same shared DSP",
            "masteringNote": None, "masteringPolicyVersion": 3,
            "masterSha256": "unused until policy passes",
            "masteringProfile": NATIVE_SHORT_MASTERING_PROFILE.receipt()}
        if policy is not None:
            record["aacEncodingPolicy"] = policy
        path = self.root / "prior.json"
        path.write_text(json.dumps(record))
        return path

    def test_encoder_consumes_recorded_pns_option_without_changing_sample_or_picture_filters(self) -> None:
        """Test the command actually passed to the owned media runner."""
        receipt = {}
        with patch.object(delivery, "observe_picture_source", return_value=self.picture), \
                patch.object(delivery, "run_audio") as run, patch.object(delivery, "_qualify") as qualify:
            delivery._encode(self.request, self.request.premaster, receipt, ("FFmpeg", "ffprobe"))
        command = run.call_args.args[0]
        policy = receipt["aacEncodingPolicy"]
        offset = command.index("-c:a")
        self.assertEqual(command[offset:offset + len(policy["arguments"])], policy["arguments"])
        self.assertEqual(command[command.index("-aac_pns") + 1], "0")
        self.assertEqual(command[command.index("-b:a") + 1], "320k")
        self.assertEqual(command[command.index("-af") + 1],
            "atrim=end_sample=1176960,asetpts=PTS-STARTPTS")
        self.assertEqual(command[command.index("-c:v") + 1], "copy")
        self.assertEqual(command[command.index("-movie_timescale") + 1], "48000")
        self.assertNotIn("-aac_ms", command)
        self.assertEqual((receipt["aacEncodeInvocations"], receipt["aacEncodesCompleted"]), (1, 1))
        qualify.assert_called_once()

    def test_old_or_changed_donor_policy_rejects_before_copying_or_media(self) -> None:
        """A compatible mastering label cannot hide unproved AAC options."""
        expected = native_aac_encoding_policy(self.request.profile)
        changed = copy.deepcopy(expected)
        changed["arguments"][-1] = "1"
        for policy in (None, {}, changed, {**expected, "schemaVersion": True}):
            with self.subTest(policy=policy), patch.object(delivery.shutil, "copyfile") as copy_file, \
                    patch.object(delivery, "run_audio") as run, \
                    self.assertRaisesRegex(RuntimeError, "AAC encoding policy"):
                request = replace(self.request, prior_receipt=self.prior(policy))
                delivery._reuse(request, {}, ("FFmpeg", "ffprobe"))
            copy_file.assert_not_called()
            run.assert_not_called()

    def test_every_recorded_candidate_requires_same_actual_encoder_policy(self) -> None:
        """Validate failed as well as selected candidate options during reuse."""
        policy = native_aac_encoding_policy(self.request.profile)
        receipt = {"aacEncodingPolicy": policy, "aacCandidatePolicy": {},
            "aacCandidates": [{"aacEncodingPolicy": copy.deepcopy(policy)} for _ in range(2)]}
        self.assertEqual(require_native_aac_policy(receipt, self.request.profile), policy)
        for index in (0, 1):
            changed = copy.deepcopy(receipt)
            changed["aacCandidates"][index]["aacEncodingPolicy"]["arguments"][-1] = "1"
            with self.subTest(index=index), self.assertRaisesRegex(RuntimeError, "AAC encoding policy"):
                require_native_aac_policy(changed, self.request.profile)
        for candidates in (None, [], [{}], [None], [{}] * 4):
            with self.subTest(candidates=candidates), self.assertRaises(RuntimeError):
                require_native_aac_policy({**receipt, "aacCandidates": candidates}, self.request.profile)

    def test_policy_arguments_are_independent_and_do_not_change_shared_profiles_or_globals(self) -> None:
        """Fresh native encoding supports both explicit bitrates without changing long-form defaults."""
        before = (dict(AUDIO), dict(ENCODE), NATIVE_SHORT_MASTERING_PROFILE.receipt())
        for profile in (NATIVE_SHORT_MASTERING_PROFILE, LEGACY_MASTERING_PROFILE):
            receipt = {}
            arguments = native_aac_arguments(profile, receipt)
            self.assertEqual(arguments[arguments.index("-b:a") + 1], profile.audio_bitrate)
            arguments[-1] = "1"
            self.assertEqual(receipt["aacEncodingPolicy"]["arguments"][-1], "0")
            receipt["aacEncodingPolicy"]["arguments"][-1] = "1"
            self.assertEqual(native_aac_encoding_policy(profile)["arguments"][-1], "0")
        self.assertEqual(before, (AUDIO, ENCODE, NATIVE_SHORT_MASTERING_PROFILE.receipt()))

    def test_signal_failure_still_stops_one_candidate_and_retains_its_actual_policy(self) -> None:
        """A failing PCM window cannot enter the true-peak correction loop."""
        signal = {"passed": False, "failedWindowIndices": [0], "inputsStable": True}
        error = delivery.ProgramDeliverySignalError("same first-window failure", signal)
        with patch.object(delivery.shutil, "which", return_value="mock-tool"), \
                patch.object(delivery, "_master", return_value=self.request.premaster), \
                patch.object(delivery, "observe_picture_source", return_value=self.picture), \
                patch.object(delivery, "run_audio", side_effect=self.write_candidate) as run, \
                patch.object(delivery, "_qualify", side_effect=error), \
                self.assertLogs("audio.native_dialogue_delivery", level="ERROR"), \
                self.assertRaises(delivery.ProgramDeliverySignalError):
            delivery.finish_native_dialogue(self.request)
        receipt = json.loads((self.request.directory / "receipt.json").read_text())
        self.assertEqual(run.call_count, 1)
        self.assertEqual(receipt["additionalAacEncodes"], 1)
        self.assertEqual(len(receipt["aacCandidates"]), 1)
        self.assertEqual(receipt["signal"], signal)
        attempt = receipt["aacCandidates"][0]
        self.assertEqual(attempt["aacEncodingPolicy"], native_aac_encoding_policy(self.request.profile))
        self.assertTrue((Path(attempt["directory"]) / "candidate.mp4").is_file())
        self.assertFalse((self.request.directory / "candidate.mp4").exists())

    @staticmethod
    def write_candidate(command: list[str]) -> None:
        """Retain fake failed encoder output without executing a media process."""
        Path(command[-1]).write_bytes(b"unqualified AAC fixture")


if __name__ == "__main__":
    unittest.main()

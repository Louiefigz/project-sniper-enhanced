"""Explicit native settings preserve default DSP and bounded, independent measurements."""
from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock, patch

from audio import float_master, master
from audio.mastering_filter import MasterFilterInput, build_master_filter
from audio.mastering_profile import (LEGACY_MASTERING_PROFILE, NATIVE_SHORT_MASTERING_PROFILE,
    MasteringProfile, resolve_mastering_profile)
from producer_config import AUDIO, ENCODE, MASTERING_POLICY_VERSION


def measured(integrated: float = -30.18, peak: float = -9.13) -> dict:
    """Use the real high-crest diagnostic's input statistics without decoding media."""
    return {"input_i": integrated, "input_tp": peak, "input_lra": 3.8,
            "input_thresh": -40.79, "target_offset": 3.24}


class MasteringProfilesTests(unittest.TestCase):
    """Settings select shared processing; they never change encoded-output acceptance gates."""

    def test_legacy_default_retains_two_dry_runs_and_exact_prior_chain(self) -> None:
        callback = Mock(side_effect=[-16.58, -15.30])
        chain, _ = master.build_pass2_afilter("unused", None, measured(), callback)
        self.assertEqual(callback.call_count, 2)
        self.assertEqual(chain, "volume=20.06dB,aresample=192000,alimiter=limit=0.794328"
            ":attack=5:release=100:level=false:latency=true")
        self.assertEqual((MASTERING_POLICY_VERSION, master.STATIC_MAX_TRIMS), (3, 2))

    def test_native_profile_reproduces_qualified_diagnostic_filter_with_six_runs(self) -> None:
        callback = Mock(side_effect=[-16.75, -15.60, -15.02, -14.67, -14.48, -14.40])
        chain, note = build_master_filter(MasterFilterInput(
            None, measured(), callback, NATIVE_SHORT_MASTERING_PROFILE))
        self.assertEqual(callback.call_count, 6)
        self.assertEqual(chain, "volume=23.10dB,aresample=192000,alimiter=limit=0.749894"
            ":attack=5:release=100:level=false:latency=true")
        self.assertIn("ceiling -2.5", note)

    def test_profiles_do_not_change_globals_or_each_others_next_request(self) -> None:
        before_audio, before_encode = dict(AUDIO), dict(ENCODE)
        for profile, count in ((NATIVE_SHORT_MASTERING_PROFILE, 6), (LEGACY_MASTERING_PROFILE, 2)):
            callback = Mock(return_value=-15)
            build_master_filter(MasterFilterInput(None, measured(), callback, profile))
            self.assertEqual(callback.call_count, count)
        self.assertEqual(AUDIO, before_audio)
        self.assertEqual(ENCODE, before_encode)

    def test_stricter_headroom_changes_linear_eligibility_without_changing_dispatch(self) -> None:
        callback = Mock(return_value=-14)
        legacy, _ = build_master_filter(MasterFilterInput(None, measured(-20, -8.2), callback))
        self.assertIn("linear=true", legacy)
        callback.assert_not_called()
        native, _ = build_master_filter(MasterFilterInput(
            None, measured(-20, -8.2), callback, NATIVE_SHORT_MASTERING_PROFILE))
        self.assertIn("alimiter", native)
        self.assertNotIn("linear=true", native)
        self.assertEqual(callback.call_count, 1)

    def test_dynamic_fallback_keeps_the_caller_prefix_and_explicit_peak(self) -> None:
        callback = Mock(side_effect=AssertionError("unexpected static run"))
        chain, _ = build_master_filter(MasterFilterInput(
            "pan=stereo|c0=c0|c1=c0", None, callback, NATIVE_SHORT_MASTERING_PROFILE))
        self.assertTrue(chain.startswith("pan=stereo|c0=c0|c1=c0,loudnorm="))
        self.assertIn("TP=-2.5", chain)

    def test_float_master_default_and_native_keep_the_same_exact_sample_clock(self) -> None:
        for profile, count in ((LEGACY_MASTERING_PROFILE, 2), (NATIVE_SHORT_MASTERING_PROFILE, 6)):
            source = float_master.FloatMasterInput("original.wav", 522240, measured(), "ffmpeg", profile)
            with patch.object(float_master, "measured_chain", return_value=-15) as observe, \
                    patch.object(float_master, "run_audio") as run:
                _, chain, _ = float_master.render_float_master(source, Path("unused"))
            self.assertEqual(observe.call_count, count)
            self.assertTrue(chain.endswith("aresample=48000,atrim=end_sample=522240,asetpts=PTS-STARTPTS"))
            self.assertIn("pcm_f32le", run.call_args.args[0])
        default = float_master.FloatMasterInput("original.wav", 1, measured(), "ffmpeg")
        self.assertIs(default.profile, LEGACY_MASTERING_PROFILE)

    def test_profile_is_immutable_and_resolver_is_closed(self) -> None:
        self.assertIs(resolve_mastering_profile("native-short-v1"), NATIVE_SHORT_MASTERING_PROFILE)
        self.assertIs(resolve_mastering_profile("default-v3"), LEGACY_MASTERING_PROFILE)
        with self.assertRaises(FrozenInstanceError):
            NATIVE_SHORT_MASTERING_PROFILE.audio_bitrate = "256k"
        for identity in ("auto", "320k", None, {"identity": "native-short-v1"}):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                resolve_mastering_profile(identity)

    def test_profile_rejects_unbounded_or_nonfinite_settings(self) -> None:
        for peak, runs, bitrate in ((float("nan"), 6, "320k"), (-1, 6, "320k"),
                                    (-2.5, 7, "320k"), (-2.5, True, "320k"), (-2.5, 6, "0k")):
            with self.subTest(peak=peak, runs=runs), self.assertRaises(ValueError):
                MasteringProfile("invalid", peak, runs, bitrate)


if __name__ == "__main__":
    unittest.main()

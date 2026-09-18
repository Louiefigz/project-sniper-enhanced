"""audio_enhance preset resolution + plan_lint audio-field gates.

Covers the cheap, deterministic surface (no ffmpeg): the AUDIO_ENHANCE preset
catalog (incl. the {models} path substitution and the `separate` dispatch
sentinel), the plan_lint acceptance/rejection of audioEnhance / audioGain, and
the music.path alternative to assetId. The actual ffmpeg / Demucs passes are
exercised by the real-audio verification runs, not here.
"""
import os
import tempfile
import unittest

from _common import *  # noqa: F401,F403


class PresetResolutionTests(unittest.TestCase):
    """build_filter: catalog lookup, {models} substitution, dispatch sentinel."""

    def test_voice_preset_resolves_to_its_chain(self) -> None:
        chain = aenh.build_filter("voice")
        self.assertIn("afftdn", chain)
        self.assertIn("highpass", chain)

    def test_models_token_substituted_with_absolute_dir(self) -> None:
        chain = aenh.build_filter("voice-rnn")
        self.assertNotIn("{models}", chain)
        self.assertIn(aenh.MODELS_DIR, chain)
        self.assertTrue(os.path.isabs(aenh.MODELS_DIR))

    def test_voice_rnn_model_file_is_vendored(self) -> None:
        chain = aenh.build_filter("voice-rnn")
        model = chain.split("arnndn=m=")[1].split(",")[0]
        self.assertTrue(os.path.isfile(model), f"missing model: {model}")

    def test_unknown_preset_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown audioEnhance preset"):
            aenh.build_filter("bogus")

    def test_separate_preset_is_dispatch_only(self) -> None:
        # `separate` routes to audio_separate via run_audio_enhance; asking
        # for its ffmpeg chain must fail loudly, never return the sentinel.
        with self.assertRaisesRegex(ValueError, "dispatch-only"):
            aenh.build_filter("separate")


class ModelsPathEscapingTests(unittest.TestCase):
    """F6: {models} is substituted UNESCAPED into the -af chain — a models dir
    containing filtergraph syntax (, ' : \\) must fail loudly NAMING the path,
    not surface later as a misleading arnndn parse error."""

    def _with_models_dir(self, path: str) -> None:
        orig = aenh.MODELS_DIR
        aenh.MODELS_DIR = path
        try:
            with self.assertRaisesRegex(ValueError, "filtergraph syntax"):
                aenh.build_filter("voice-rnn")
        finally:
            aenh.MODELS_DIR = orig

    def test_comma_path_fails_loudly_naming_the_path(self) -> None:
        orig = aenh.MODELS_DIR
        aenh.MODELS_DIR = "/tmp/weird,dir/models"
        try:
            with self.assertRaisesRegex(ValueError, "weird,dir"):
                aenh.build_filter("voice-rnn")
        finally:
            aenh.MODELS_DIR = orig

    def test_colon_and_quote_and_backslash_fail(self) -> None:
        for bad in ("/tmp/we:ird/models", "/tmp/o'brien/models",
                    "/tmp/back\\slash/models"):
            self._with_models_dir(bad)

    def test_clean_path_presets_unaffected(self) -> None:
        # Chains without {models} never touch the guard, whatever MODELS_DIR is.
        orig = aenh.MODELS_DIR
        aenh.MODELS_DIR = "/tmp/weird,dir/models"
        try:
            self.assertIn("afftdn", aenh.build_filter("voice"))
        finally:
            aenh.MODELS_DIR = orig


class AudioEnhanceLintTests(unittest.TestCase):
    """plan_lint must accept catalog presets and reject anything else."""

    def _errors(self, plan: dict) -> list[str]:
        return pl.lint(plan, MANIFEST).errors

    def assert_fires(self, plan: dict, needle: str) -> None:
        errors = self._errors(plan)
        self.assertTrue(any(needle in e for e in errors),
                        f"expected {needle!r} in errors: {errors}")

    def test_valid_preset_passes(self) -> None:
        plan = good_plan()
        plan["audioEnhance"] = {"preset": "voice"}
        self.assertEqual(self._errors(plan), [])

    def test_separate_preset_passes_lint(self) -> None:
        plan = good_plan()
        plan["audioEnhance"] = {"preset": "separate"}
        self.assertEqual(self._errors(plan), [])

    def test_unknown_preset_fires(self) -> None:
        plan = good_plan()
        plan["audioEnhance"] = {"preset": "bogus"}
        self.assert_fires(plan, "audioEnhance.preset")

    def test_non_object_fires(self) -> None:
        plan = good_plan()
        plan["audioEnhance"] = "voice"
        self.assert_fires(plan, "audioEnhance must be an object")

    def test_audio_authority_mode_is_closed_vocabulary(self) -> None:
        plan = good_plan()
        plan["audioAuthorityMode"] = "mastered-stereo"
        self.assertEqual(self._errors(plan), [])
        plan["audioAuthorityMode"] = "stems-ish"
        self.assert_fires(plan, "audioAuthorityMode")


class AudioGainLintTests(unittest.TestCase):
    """audioGain windows: shape, dB bounds, output-duration bounds, overlap."""

    def _errors(self, plan: dict) -> list[str]:
        return pl.lint(plan, MANIFEST).errors

    def assert_fires(self, plan: dict, needle: str) -> None:
        errors = self._errors(plan)
        self.assertTrue(any(needle in e for e in errors),
                        f"expected {needle!r} in errors: {errors}")

    def test_valid_window_passes(self) -> None:
        plan = good_plan()   # 30s output
        plan["audioGain"] = [{"outStart": 5.0, "outEnd": 8.0, "dB": -3.0}]
        self.assertEqual(self._errors(plan), [])

    def test_inverted_window_fires(self) -> None:
        plan = good_plan()
        plan["audioGain"] = [{"outStart": 8.0, "outEnd": 5.0, "dB": -3.0}]
        self.assert_fires(plan, "audioGain")

    def test_non_numeric_field_fires(self) -> None:
        plan = good_plan()
        plan["audioGain"] = [{"outStart": "loud", "outEnd": 5.0, "dB": -3.0}]
        self.assert_fires(plan, "audioGain")

    def test_insane_db_fires(self) -> None:
        plan = good_plan()
        plan["audioGain"] = [{"outStart": 5.0, "outEnd": 8.0, "dB": 40.0}]
        self.assert_fires(plan, "audioGain")

    def test_window_beyond_output_duration_fires(self) -> None:
        plan = good_plan()   # output is 30s
        plan["audioGain"] = [{"outStart": 5.0, "outEnd": 300.0, "dB": -3.0}]
        self.assert_fires(plan, "outside output duration")

    def test_overlapping_windows_fire(self) -> None:
        plan = good_plan()
        plan["audioGain"] = [{"outStart": 5.0, "outEnd": 8.0, "dB": -3.0},
                             {"outStart": 7.0, "outEnd": 9.0, "dB": 2.0}]
        self.assert_fires(plan, "overlap")


class MusicPathLintTests(unittest.TestCase):
    """music.path (absolute existing file) as the assetId alternative."""

    def _errors(self, plan: dict) -> list[str]:
        return pl.lint(plan, MANIFEST).errors

    def assert_fires(self, plan: dict, needle: str) -> None:
        errors = self._errors(plan)
        self.assertTrue(any(needle in e for e in errors),
                        f"expected {needle!r} in errors: {errors}")

    def test_absolute_existing_path_passes(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp3") as fh:
            plan = good_plan()
            plan["music"] = {"enabled": True, "path": fh.name}
            self.assertEqual(self._errors(plan), [])

    def test_relative_path_fires(self) -> None:
        plan = good_plan()
        plan["music"] = {"enabled": True, "path": "tracks/bed.mp3"}
        self.assert_fires(plan, "music.path")

    def test_nonexistent_path_fires(self) -> None:
        plan = good_plan()
        plan["music"] = {"enabled": True, "path": "/nope/never/bed.mp3"}
        self.assert_fires(plan, "music.path")

    def test_no_path_asset_or_vibe_fires(self) -> None:
        plan = good_plan()
        plan["music"] = {"enabled": True}
        self.assert_fires(plan, "neither path, assetId nor vibe")

    def test_asset_id_still_checked_when_path_absent(self) -> None:
        plan = good_plan()
        plan["music"] = {"enabled": True, "assetId": "nope-1"}
        self.assert_fires(plan, "not in manifest")

    def test_bad_gap_db_fires(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp3") as fh:
            plan = good_plan()
            plan["music"] = {"enabled": True, "path": fh.name, "gapDb": "quiet"}
            self.assert_fires(plan, "music.gapDb")

    def test_music_cannot_equal_or_exceed_dialogue(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp3") as fh:
            plan = good_plan()
            plan["music"] = {"enabled": True, "path": fh.name, "gapDb": 0}
            self.assert_fires(plan, "music.gapDb")

    def test_three_db_voice_priority_is_the_hottest_legal_mix(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp3") as fh:
            plan = good_plan()
            plan["music"] = {"enabled": True, "path": fh.name, "gapDb": 3}
            self.assertEqual(self._errors(plan), [])

    def test_bad_duck_fires(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp3") as fh:
            plan = good_plan()
            plan["music"] = {"enabled": True, "path": fh.name, "duck": "yes"}
            self.assert_fires(plan, "music.duck")

    def test_disabling_ducking_is_rejected_for_voice_first_output(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp3") as fh:
            plan = good_plan()
            plan["music"] = {"enabled": True, "path": fh.name, "duck": False}
            self.assert_fires(plan, "music.duck=false")


if __name__ == "__main__":
    unittest.main(verbosity=2)

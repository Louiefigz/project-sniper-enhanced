"""Pure finishing-vocabulary contract: explicit rejection, exact projection, no media."""
from __future__ import annotations

import copy
import unittest
import tempfile
from pathlib import Path
from dataclasses import replace
from unittest import mock

from audio.program_finish_bus import assert_finishing_stable, cue_start_sample, finishing_identity, validate_finishing_record
from audio.program_finish_contract import (FINISHING_POLICY_VERSION, SfxCue, finishing_free_plan,
    finishing_reason, finishing_request, finishing_settings, requested_settings)
from audio.render_audio_authority import SOURCE_FLOAT_POLICY, SOURCE_FLOAT_POLICY_V2, audio_policy_reason
from cut_preview_io import file_hash

PLAIN = {"cutTrack": [{"sourceId": "a", "start": 0, "end": 4}]}
VALID = {**PLAIN, "audioEnhance": {"preset": "voice"},
         "audioGain": [{"outStart": 1.0, "outEnd": 1.5, "dB": 6, "rationale": "lift"}]}
HISTORICAL = {**VALID, "transitions": [{"outTime": 1.0, "kind": "white-flash", "sfx": True},
                         {"outTime": 2.5, "kind": "white-flash", "sfx": "click"}]}


class FinishingReasonTests(unittest.TestCase):
    """Audio vocabulary validation is separate from executable visual admission."""

    def test_absent_and_valid_finishing_have_no_reason(self) -> None:
        self.assertIsNone(finishing_reason(PLAIN))
        self.assertIsNone(finishing_reason(VALID))
        self.assertIsNone(finishing_reason({**PLAIN, "audioGain": [], "transitions": []}))

    def test_unknown_dispatch_and_malformed_enhance_reject(self) -> None:
        cases = {"unknown": {"preset": "light"}, "dispatch": {"preset": "separate"},
                 "shape": {"preset": "voice", "extra": 1}, "type": "voice", "missing": {"rationale": "x"}}
        for label, value in cases.items():
            with self.subTest(label=label):
                reason = finishing_reason({**PLAIN, "audioEnhance": value})
                self.assertIsNotNone(reason)
                self.assertIn("audioEnhance", reason)
        self.assertIn("downloaded model weights", finishing_reason({**PLAIN, "audioEnhance": {"preset": "separate"}}))

    def test_gain_windows_reuse_the_executor_validator(self) -> None:
        cases = {"fields": [{"start": 0, "end": 1, "gainDb": 1}], "order": [{"outStart": 2, "outEnd": 1, "dB": 1}],
                 "range": [{"outStart": 0, "outEnd": 1, "dB": 13}], "type": {"outStart": 0},
                 "overlap": [{"outStart": 0, "outEnd": 2, "dB": 1}, {"outStart": 1, "outEnd": 3, "dB": 1}]}
        for label, value in cases.items():
            with self.subTest(label=label):
                reason = finishing_reason({**PLAIN, "audioGain": value})
                self.assertIsNotNone(reason)
                self.assertTrue(reason.startswith("audioGain"))
        self.assertIn("overlap", finishing_reason({**PLAIN, "audioGain": cases["overlap"]}))

    def test_gain_fields_reject_coercion_nonfinite_and_overflow_before_finishing(self) -> None:
        """Direct producer callers must reject malformed gain without relying on TS."""
        invalid = (False, True, None, "2", "NaN", float("nan"), float("inf"), -float("inf"), 10**1000)
        cases = [(field, value) for field in ("outStart", "outEnd", "dB") for value in invalid]
        for field, value in cases:
            with self.subTest(field=field, valueType=type(value).__name__):
                plan = {**PLAIN, "audioGain": [{"outStart": 0, "outEnd": 1, "dB": 2, field: value}]}
                self.assertIn("numeric", finishing_reason(plan))
                self.assertRaisesRegex(RuntimeError, "numeric", finishing_request, plan, 4.0)

    def test_sfx_must_be_boolean_or_built_pack_name(self) -> None:
        for value in ("bang", 1, 0.5, ["click"], {"name": "click"}):
            with self.subTest(value=value):
                reason = finishing_reason({**PLAIN, "transitions": [{"outTime": 1, "kind": "white-flash", "sfx": value}]})
                self.assertIsNotNone(reason)
                self.assertIn("transitions[0].sfx", reason)
        self.assertEqual(finishing_reason({**PLAIN, "transitions": "x"}), "transitions must be a list")
        self.assertEqual(finishing_reason({**PLAIN, "transitions": [1]}), "transitions[0] must be an object")

    def test_v2_policy_admits_valid_finishing_and_v1_still_refuses(self) -> None:
        self.assertIsNone(audio_policy_reason(VALID, SOURCE_FLOAT_POLICY_V2))
        self.assertIn("has not qualified", audio_policy_reason(VALID, SOURCE_FLOAT_POLICY))
        bad = {**PLAIN, "audioGain": [{"start": 0, "end": 1, "gainDb": 1}]}
        self.assertTrue(audio_policy_reason(bad, SOURCE_FLOAT_POLICY_V2).startswith("source-float-v2 rejects audioGain"))
        for effect in ({"audioEnhance": {"preset": "separate"}},
                       {"transitions": [{"outTime": 1, "kind": "white-flash", "sfx": "bang"}]}):
            with self.subTest(effect=effect):
                self.assertIn("rejects", audio_policy_reason({**PLAIN, **effect}, SOURCE_FLOAT_POLICY_V2))


class FinishingProjectionTests(unittest.TestCase):
    """Base picture and raw bus ignore finishing; the request binds the exact duration."""

    def test_finishing_free_plan_strips_only_finishing_fields(self) -> None:
        before = copy.deepcopy(HISTORICAL)
        stripped = finishing_free_plan(HISTORICAL)
        self.assertEqual(HISTORICAL, before)
        self.assertNotIn("audioEnhance", stripped)
        self.assertNotIn("audioGain", stripped)
        self.assertEqual(stripped["transitions"], [{"outTime": 1.0, "kind": "white-flash"},
                                                    {"outTime": 2.5, "kind": "white-flash"}])
        self.assertEqual(stripped["cutTrack"], VALID["cutTrack"])
        self.assertEqual(finishing_free_plan(PLAIN), PLAIN)

    def test_request_is_none_without_finishing_and_bound_with_it(self) -> None:
        self.assertIsNone(finishing_request(PLAIN, 4.004))
        self.assertIsNone(finishing_request({**PLAIN, "audioGain": [], "transitions": []}, 4.004))
        request = finishing_request(VALID, 4.004)
        self.assertEqual(request.enhance_preset, "voice")
        self.assertIn("afftdn", request.enhance_chain)
        self.assertEqual([(w.out_start, w.out_end, w.db) for w in request.gain], [(1.0, 1.5, 6.0)])
        self.assertEqual(request.sfx, ())

    def test_rnn_preset_binds_the_vendored_model_path(self) -> None:
        request = finishing_request({**PLAIN, "audioEnhance": {"preset": "voice-rnn"}}, 4.0)
        self.assertIn("arnndn=m=/", request.enhance_chain)
        self.assertNotIn("{models}", request.enhance_chain)

    def test_out_of_program_gain_and_invalid_duration_reject(self) -> None:
        with self.assertRaisesRegex(RuntimeError, r"audioGain\[0\].*outside the 4\.004s program"):
            finishing_request({**PLAIN, "audioGain": [{"outStart": 3.9, "outEnd": 4.2, "dB": 1}]}, 4.004)
        with self.assertRaisesRegex(RuntimeError, "rejects audioEnhance preset 'separate'"):
            finishing_request({**PLAIN, "audioEnhance": {"preset": "separate"}}, 4.004)
        for duration in (0.0, -1.0, 4, "4.0"):
            with self.subTest(duration=duration), self.assertRaises(RuntimeError):
                finishing_request(VALID, duration)

    def test_settings_are_canonical_and_repeatable(self) -> None:
        settings = requested_settings(VALID, 4.004)
        self.assertEqual(settings, finishing_settings(finishing_request(VALID, 4.004)))
        self.assertEqual(settings, {"policyVersion": FINISHING_POLICY_VERSION, "audioEnhance": {"preset": "voice"},
            "audioGain": [{"outStart": 1.0, "outEnd": 1.5, "dB": 6.0}],
            "sfx": []})
        self.assertIsNone(requested_settings(PLAIN, 4.004))
        changed = copy.deepcopy(VALID)
        changed["audioGain"][0]["dB"] = 5
        self.assertNotEqual(settings, requested_settings(changed, 4.004))

    def test_inert_sfx_dto_settings_preserve_exact_projection(self) -> None:
        """Historical sound metadata has no visual admission or executable plan."""
        request = replace(finishing_request(VALID, 4.004), sfx=(
            SfxCue(1.0, True, 0.3, None), SfxCue(2.5, "click", 0.01, "TEST-ONLY")))
        self.assertEqual(finishing_settings(request)["sfx"], [
            {"outTime": 1.0, "sfx": True, "leadS": 0.3},
            {"outTime": 2.5, "sfx": "click", "leadS": 0.01}])

    def test_retired_transitions_reject_before_media_even_without_sound(self) -> None:
        for kind in ("white-flash", "light-leak", "zoom-pull"):
            for sound in (False, True, "click"):
                plan = {**VALID, "transitions": [{"outTime": 1.0, "kind": kind, "sfx": sound}]}
                with self.subTest(kind=kind, sound=sound), mock.patch("subprocess.run") as run:
                    with self.assertRaisesRegex(RuntimeError, "transitions.*retired"):
                        finishing_request(plan, 4.004)
                    run.assert_not_called()

    def test_cue_start_lands_the_hit_on_the_seam_and_never_before_zero(self) -> None:
        self.assertEqual(cue_start_sample(SfxCue(1.0, True, 0.3, None)), 33600)
        self.assertEqual(cue_start_sample(SfxCue(2.5, "click", 0.01, "x")), 119520)
        self.assertEqual(cue_start_sample(SfxCue(0.1, True, 0.3, None)), 0)


class FinishingRecordTests(unittest.TestCase):
    """Receipt identity omits paths; a malformed or relabelled record cannot load."""

    RECORD = {"policyVersion": FINISHING_POLICY_VERSION, "order": "cleanup->gain->sfx->music->master",
        "settings": {"policyVersion": 1}, "detectorKey": "finished-dialogue-without-sfx",
        "cleanup": {"preset": "voice-rnn", "filter": "f", "measuredLatencySamples": 480,
                    "model": {"path": "/m/bd.rnnn", "sha256": "m" * 64}},
        "gain": {"filter": "g", "rampS": 0.05, "envelopeFrameSamples": 256},
        "sfx": {"cues": [{"outTime": 1.0, "sfx": True, "leadS": 0.3, "startSample": 33600, "source": "engine-whoosh"}],
                "sources": {"engine-whoosh": {"path": "/bus/x/engine-whoosh.wav", "sha256": "w" * 64, "leadS": 0.3}}},
        "dialogue": {"path": "/bus/x/dialogue-finished.wav", "sha256": "d" * 64},
        "program": {"path": "/bus/x/program-finished.wav", "sha256": "p" * 64}}

    def test_identity_is_path_free_and_complete(self) -> None:
        identity = finishing_identity(self.RECORD)
        self.assertNotIn("path", str(identity))
        self.assertEqual(identity["cleanup"]["modelSha256"], "m" * 64)
        self.assertEqual(identity["sfx"]["sources"]["engine-whoosh"], {"sha256": "w" * 64, "leadS": 0.3})
        self.assertEqual((identity["dialogueSha256"], identity["programSha256"]), ("d" * 64, "p" * 64))
        self.assertIsNone(finishing_identity(None))

    def test_inert_retained_sfx_source_drift_rejects_without_media(self) -> None:
        """Synthetic byte records test archive integrity, never visual admission."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            stem = root / "TEST-stem"
            stem.write_bytes(b"TEST ONLY inert retained stem")
            binding = {"path": str(stem), "sha256": file_hash(stem)}
            sources = {}
            for label in ("engine-whoosh", "click"):
                path = root / label
                path.write_bytes(b"TEST ONLY inert retained sound")
                sources[label] = {"path": str(path), "sha256": file_hash(path)}
            record = {"cleanup": None, "sfx": {"sources": sources},
                      "dialogue": binding, "program": binding}
            assert_finishing_stable(record)
            for label, source in sources.items():
                path = Path(source["path"])
                before = path.read_bytes()
                path.write_bytes(before + b"changed")
                with self.subTest(source=label), mock.patch("subprocess.run") as run:
                    with self.assertRaisesRegex(RuntimeError, f"SFX source {label} bytes changed"):
                        assert_finishing_stable(record)
                    run.assert_not_called()
                path.write_bytes(before)
            assert_finishing_stable(record)

    def test_malformed_or_relabelled_record_rejects_before_any_artifact_read(self) -> None:
        for mutate in ({"policyVersion": 2}, {"order": "sfx->cleanup"}, {"detectorKey": "raw"},
                       {"extra": 1}, {"program": {"path": "/bus/x/program-finished.wav"}}):
            record = {**copy.deepcopy(self.RECORD), **mutate}
            with self.subTest(mutate=mutate), self.assertRaisesRegex(RuntimeError, "malformed|stale"):
                validate_finishing_record(record, None, lambda value: None)
        with self.assertRaises(RuntimeError):
            validate_finishing_record("not a record", None, lambda value: None)


if __name__ == "__main__":
    unittest.main(verbosity=2)

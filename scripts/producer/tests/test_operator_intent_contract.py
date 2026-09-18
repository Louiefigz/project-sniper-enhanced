"""Deterministic operator-intent identity and lane-coverage tests."""
import copy
import unittest

from _common import *  # noqa: F401,F403
import operator_intent_contract as contract
from transcript_cut_contract import _check_previsual


EXPECTED = {
    "mode": "longform",
    "scope": "produced",
    "lanes": {},
    "music": False,
    "audioEnhance": {"preset": "voice"},
}

PLAN = {
    "target": {"mode": "longform", "scope": "produced"},
    "cutTrack": [
        {"sourceId": "raw-1", "start": 0, "end": 8, "speed": 1},
        {"sourceId": "raw-1", "start": 9, "end": 20, "speed": 1},
    ],
    "punchIns": [{"outStart": 2, "outEnd": 3}],
    "graphicsTrack": [{"outStart": 4, "outEnd": 7, "kind": "statement-card"}],
    "transitions": [{"outTime": 8, "kind": "flash"}],
    "captions": {"burn": False},
    "brollTrack": [{"outStart": 10, "outEnd": 12, "assetId": "broll-1"}],
    "music": {"enabled": False},
    "audioEnhance": {"preset": "voice"},
}


class OperatorIntentContractTests(unittest.TestCase):
    def test_requested_music_stays_deferred_until_full_finishing_gate(self) -> None:
        """Pure real gate functions; no source, media, or acceptance is simulated."""
        expected = {"mode": "longform", "scope": "trim", "lanes": {}, "music": True}
        plan = {"planVersion": 1, "target": copy.deepcopy(expected),
                "cutTrack": [{"sourceId": "TEST", "start": 0, "end": 1, "speed": 1}],
                "cutDecisions": {"schemaVersion": 1, "removals": []}}
        original = copy.deepcopy(plan)
        errors = []
        _check_previsual(plan, errors)
        self.assertEqual(errors, [])
        self.assertIn("plan.music.enabled does not match stored operator intent",
                      contract.evaluate(plan, expected)["errors"])
        candidate = copy.deepcopy(plan)
        candidate["music"] = {"enabled": True, "assetId": "TEST-admitted-choice"}
        self.assertTrue(contract.evaluate(candidate, expected)["ok"])
        _check_previsual(candidate, errors)
        self.assertTrue(any("populated downstream fields: music" in error for error in errors))
        self.assertEqual(plan, original)

    def test_target_music_cannot_replace_actual_stored_operator_intent(self) -> None:
        expected = {"mode": "longform", "scope": "trim", "lanes": {}, "music": False}
        plan = {"target": {**expected, "music": True},
                "music": {"enabled": True, "assetId": "TEST"}}
        self.assertIn("plan.music.enabled does not match stored operator intent",
                      contract.evaluate(plan, expected)["errors"])

    def test_matching_produced_plan_passes(self) -> None:
        self.assertTrue(contract.evaluate(PLAN, EXPECTED)["ok"])

    def test_scope_downgrade_fails(self) -> None:
        plan = copy.deepcopy(PLAN)
        plan["target"]["scope"] = "light"
        errors = contract.evaluate(plan, EXPECTED)["errors"]
        self.assertTrue(any("target.scope" in error for error in errors), errors)

    def test_mode_drift_fails(self) -> None:
        plan = copy.deepcopy(PLAN)
        plan["target"]["mode"] = "short"
        errors = contract.evaluate(plan, EXPECTED)["errors"]
        self.assertTrue(any("target.mode" in error for error in errors), errors)

    def test_pace_style_and_reference_identity_match(self) -> None:
        expected = copy.deepcopy(EXPECTED)
        expected.update({
            "pace": "jadenly",
            "style": "jadenly",
            "reference": {"id": "reference-1", "strategy": "extend"},
        })
        plan = copy.deepcopy(PLAN)
        plan["target"].update({
            "pace": "jadenly",
            "style": "jadenly",
            "referenceId": "reference-1",
            "referenceStrategy": "extend",
        })
        self.assertTrue(contract.evaluate(plan, expected)["ok"])
        for field, value in (
            ("pace", "caleb"),
            ("style", "caleb"),
            ("referenceId", "reference-2"),
            ("referenceStrategy", "mimic"),
        ):
            changed = copy.deepcopy(plan)
            changed["target"][field] = value
            errors = contract.evaluate(changed, expected)["errors"]
            self.assertTrue(any(field in error for error in errors), errors)

    def test_missing_requested_lane_fails(self) -> None:
        plan = copy.deepcopy(PLAN)
        plan["brollTrack"] = []
        errors = contract.evaluate(plan, EXPECTED)["errors"]
        self.assertTrue(any("broll" in error and "no broll" in error for error in errors), errors)

    def test_produced_longform_rejects_bare_empty_transitions(self) -> None:
        plan = copy.deepcopy(PLAN)
        plan["transitions"] = []
        verdict = contract.evaluate(plan, EXPECTED)
        self.assertFalse(verdict["ok"], verdict["errors"])
        self.assertFalse(verdict["metrics"]["laneCoverage"]["transitions"])
        self.assertFalse(verdict["metrics"]["laneEvidence"]["transitions"])
        self.assertEqual(verdict["metrics"]["transitionDecision"],
                         "unjustified-empty")

    def test_clean_hook_receipt_cannot_replace_checked_transition_lane(self) -> None:
        plan = copy.deepcopy(PLAN)
        plan["transitions"] = []
        plan["transitionRationale"] = {
            "decision": "clean-hook",
            "reason": "The continuous sentence reads cleaner as a hard cut.",
            "seams": [{"outTime": 8.0,
                       "evidence": "Continuous delivery across the seam"}],
        }
        verdict = contract.evaluate(plan, EXPECTED)
        self.assertFalse(verdict["ok"], verdict["errors"])
        self.assertFalse(verdict["metrics"]["laneCoverage"]["transitions"])
        self.assertEqual(verdict["metrics"]["transitionDecision"], "clean-hook")

        plan["transitionRationale"]["seams"][0]["outTime"] = 9.0
        verdict = contract.evaluate(plan, EXPECTED)
        self.assertFalse(verdict["ok"], verdict["errors"])
        self.assertEqual(verdict["metrics"]["transitionDecision"],
                         "unjustified-empty")

    def test_checked_transition_must_land_on_an_intro_seam(self) -> None:
        plan = copy.deepcopy(PLAN)
        plan["transitions"] = [{"outTime": 80, "kind": "white-flash"}]
        verdict = contract.evaluate(plan, EXPECTED)
        self.assertFalse(verdict["ok"], verdict["errors"])
        self.assertFalse(verdict["metrics"]["laneEvidence"]["transitions"])

    def test_motion_requires_a_real_punch_in(self) -> None:
        plan = copy.deepcopy(PLAN)
        plan["punchIns"] = []
        plan["treatmentMap"] = [
            {"outStart": 1, "outEnd": 4, "treatment": "kinetic"},
        ]
        errors = contract.evaluate(plan, EXPECTED)["errors"]
        self.assertTrue(any("motion" in error and "no motion" in error
                            for error in errors), errors)

    def test_longform_caption_evidence_matches_the_rendered_lane(self) -> None:
        plan = copy.deepcopy(PLAN)
        plan.pop("captions")
        self.assertTrue(contract.evaluate(plan, EXPECTED)["ok"])
        expected = copy.deepcopy(EXPECTED)
        expected["lanes"] = {"captions": "off"}
        plan["target"]["lanes"] = {"captions": "off"}
        verdict = contract.evaluate(plan, expected)
        self.assertTrue(verdict["ok"], verdict["errors"])
        self.assertFalse(verdict["metrics"]["laneEvidence"]["captions"])

    def test_captions_track_is_rejected_and_never_counts_as_evidence(self) -> None:
        expected = copy.deepcopy(EXPECTED)
        expected["mode"] = "short"
        plan = copy.deepcopy(PLAN)
        plan["target"]["mode"] = "short"
        plan["captions"] = {"burn": False}
        plan["captionsTrack"] = [
            {"outStart": 0, "outEnd": 2, "text": "This will not render"},
        ]
        verdict = contract.evaluate(plan, expected)
        self.assertFalse(verdict["ok"], verdict["errors"])
        self.assertFalse(verdict["metrics"]["laneEvidence"]["captions"])
        self.assertTrue(any("captionsTrack is not renderable" in error
                            for error in verdict["errors"]), verdict["errors"])
        self.assertTrue(any("no captions coverage" in error
                            for error in verdict["errors"]), verdict["errors"])

    def test_empty_captions_track_is_backward_compatible(self) -> None:
        plan = copy.deepcopy(PLAN)
        plan["captionsTrack"] = []
        self.assertTrue(contract.evaluate(plan, EXPECTED)["ok"])

    def test_strict_caption_track_counts_only_when_its_delivery_is_real(self) -> None:
        expected = copy.deepcopy(EXPECTED)
        expected["mode"] = "short"
        plan = copy.deepcopy(PLAN)
        plan["target"]["mode"] = "short"
        plan["captions"] = {"burn": True}
        plan["captionsTrack"] = {
            "schemaVersion": 1,
            "source": "kept-transcript",
            "defaultPolicy": "karaoke",
            "groups": [],
        }
        verdict = contract.evaluate(plan, expected)
        self.assertTrue(verdict["ok"], verdict["errors"])
        plan["captions"]["burn"] = False
        verdict = contract.evaluate(plan, expected)
        self.assertFalse(verdict["ok"])
        self.assertFalse(verdict["metrics"]["laneEvidence"]["captions"])

    def test_auto_transitions_missing_or_malformed_still_fail(self) -> None:
        for value, decision in ((None, "missing"), ({}, "malformed")):
            plan = copy.deepcopy(PLAN)
            if value is None:
                plan.pop("transitions")
            else:
                plan["transitions"] = value
            verdict = contract.evaluate(plan, EXPECTED)
            self.assertFalse(verdict["ok"])
            self.assertEqual(verdict["metrics"]["transitionDecision"], decision)
            self.assertTrue(any("transitions" in error for error in verdict["errors"]),
                            verdict["errors"])

    def test_explicit_transition_omission_does_not_waive_other_lanes(self) -> None:
        plan = copy.deepcopy(PLAN)
        plan["transitions"] = []
        plan["graphicsTrack"] = []
        verdict = contract.evaluate(plan, EXPECTED)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("graphics" in error for error in verdict["errors"]),
                        verdict["errors"])

    def test_waived_lane_must_be_stamped_and_absent(self) -> None:
        expected = copy.deepcopy(EXPECTED)
        expected["lanes"] = {"broll": "off"}
        plan = copy.deepcopy(PLAN)
        plan["target"]["lanes"] = {"broll": "off"}
        errors = contract.evaluate(plan, expected)["errors"]
        self.assertTrue(any("is 'off'" in error for error in errors), errors)
        plan["brollTrack"] = []
        self.assertTrue(contract.evaluate(plan, expected)["ok"])

    def test_missing_target_never_infers_intent(self) -> None:
        errors = contract.evaluate({}, EXPECTED)["errors"]
        self.assertTrue(any("target is missing" in error for error in errors), errors)

    def test_finish_settings_match_operator(self) -> None:
        plan = copy.deepcopy(PLAN)
        plan["music"]["enabled"] = True
        plan["audioEnhance"] = {"preset": "voice-rnn"}
        errors = contract.evaluate(plan, EXPECTED)["errors"]
        self.assertTrue(any("music.enabled" in error for error in errors), errors)
        self.assertTrue(any("audioEnhance" in error for error in errors), errors)

    def test_unspecified_finish_settings_stay_off(self) -> None:
        expected = {key: value for key, value in EXPECTED.items()
                    if key not in ("music", "audioEnhance")}
        plan = copy.deepcopy(PLAN)
        plan.pop("audioEnhance")
        self.assertTrue(contract.evaluate(plan, expected)["ok"])
        plan["music"]["enabled"] = True
        self.assertTrue(any("music.enabled" in error
                            for error in contract.evaluate(plan, expected)["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

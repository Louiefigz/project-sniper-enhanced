#!/usr/bin/env python3
"""Focused contract tests for the route-side reference profile gate."""

import unittest

from _common import *  # noqa: F401,F403

import reference_profile_lint as rpl


EXPECTED = rpl.Expected("ref-123", "short", "mimic")


def plan() -> dict:
    """A 60-second plan with deterministic event counts/rates."""
    return {
        "target": {
            "mode": "short",
            "referenceId": "ref-123",
            "referenceStrategy": "mimic",
        },
        "cutTrack": [
            {"start": i * 12.0, "end": (i + 1) * 12.0, "speed": 1.0}
            for i in range(5)
        ],
        "titleCards": [{"outStart": 0.0}],
        "graphicsTrack": [{"outStart": 5.0}, {"outStart": 20.0}],
        "punchIns": [{"outStart": 12.0}],
        "transitions": [],
    }


def profile() -> dict:
    """Canonical backend profile shape with all comparison lanes populated."""
    return {
        "schemaVersion": 1,
        "referenceId": "ref-123",
        "title": "Reference",
        "source": {"durationS": 60.0},
        "suggestedMode": "short",
        "mechanics": {
            "cutsPerMin": 10.0,
            "eventRatesPerMin": {
                "graphic-in": 5.0,
                "panel-in": 1.0,
                "punch": 0.0,
            },
            "transitionClasses": {"hard-cut": 10, "sweep": 1, "flash": 1},
        },
        "quality": {"ready": True},
        "representativeFrames": ["states/001.jpg"],
    }


class ReferenceIdentityTests(unittest.TestCase):
    def test_matching_contract_passes(self) -> None:
        verdict = rpl.lint(plan(), profile(), EXPECTED)
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual(verdict["errors"], [])

    def test_missing_plan_identity_fails(self) -> None:
        value = plan()
        del value["target"]["referenceId"]
        verdict = rpl.lint(value, profile(), EXPECTED)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("target.referenceId" in error for error in verdict["errors"]))

    def test_profile_identity_fails_but_suggested_mode_is_advisory(self) -> None:
        value = profile()
        value["referenceId"] = "other"
        value["suggestedMode"] = "longform"
        verdict = rpl.lint(plan(), value, EXPECTED)
        self.assertTrue(any("profile.referenceId" in error for error in verdict["errors"]))
        self.assertFalse(any("suggestedMode" in error for error in verdict["errors"]))
        self.assertTrue(any("operator-confirmed" in warning for warning in verdict["warnings"]))

    def test_suggested_mode_alone_never_blocks_operator_override(self) -> None:
        value = profile()
        value["suggestedMode"] = "longform"
        verdict = rpl.lint(plan(), value, EXPECTED)
        self.assertTrue(verdict["ok"], verdict)
        self.assertTrue(any("operator-confirmed" in warning for warning in verdict["warnings"]))

    def test_strategy_mismatch_fails(self) -> None:
        value = plan()
        value["target"]["referenceStrategy"] = "extend"
        errors = rpl.lint(value, profile(), EXPECTED)["errors"]
        self.assertTrue(any("target.referenceStrategy" in error for error in errors))

    def test_mimic_rejects_closed_style_injection(self) -> None:
        value = plan()
        value["target"]["style"] = "caleb"
        errors = rpl.lint(value, profile(), EXPECTED)["errors"]
        self.assertTrue(any("target.style" in error for error in errors))

    def test_extend_requires_exact_closed_style(self) -> None:
        value = plan()
        value["target"]["referenceStrategy"] = "extend"
        expected = rpl.Expected("ref-123", "short", "extend", "caleb")
        self.assertTrue(any("target.style" in error for error in rpl.lint(value, profile(), expected)["errors"]))
        value["target"]["style"] = "caleb"
        value["target"]["pace"] = "caleb"
        self.assertTrue(rpl.lint(value, profile(), expected)["ok"])

    def test_extend_rejects_contradictory_pace(self) -> None:
        value = plan()
        value["target"].update({
            "referenceStrategy": "extend", "style": "caleb", "pace": "angela",
        })
        expected = rpl.Expected("ref-123", "short", "extend", "caleb")
        errors = rpl.lint(value, profile(), expected)["errors"]
        self.assertTrue(any("target.pace" in error for error in errors))


class ReferenceRateTests(unittest.TestCase):
    def test_severe_mimic_divergence_fails(self) -> None:
        value = plan()
        value["cutTrack"] = []
        value["target"]["durationTargetS"] = 60.0
        dense = profile()
        dense["mechanics"]["cutsPerMin"] = 20.0
        dense["mechanics"]["eventRatesPerMin"] = {
            "graphic": 30.0, "punch": 15.0, "transition": 10.0,
        }
        verdict = rpl.lint(value, dense, EXPECTED)
        self.assertFalse(verdict["ok"])
        self.assertGreaterEqual(len([e for e in verdict["errors"] if "mimic rate" in e]), 3)

    def test_mimic_cannot_omit_a_dense_graphics_system(self) -> None:
        value = plan()
        value["titleCards"] = []
        value["graphicsTrack"] = []
        dense = profile()
        dense["mechanics"]["cutsPerMin"] = None
        dense["mechanics"]["eventRatesPerMin"] = {"graphic": 30.0}
        dense["mechanics"]["transitionClasses"] = {}
        errors = rpl.lint(value, dense, EXPECTED)["errors"]
        self.assertTrue(any("graphics system" in error for error in errors))

    def test_available_rates_warn_without_failing(self) -> None:
        verdict = rpl.lint(plan(), profile(), EXPECTED)
        self.assertTrue(verdict["ok"])
        warning_text = " | ".join(verdict["warnings"])
        for lane in ("cuts", "graphics", "punches", "transitions"):
            self.assertIn(f"reference rate {lane}", warning_text)
        self.assertEqual(verdict["metrics"]["planRatesPerMin"], {
            "cuts": 4.0, "graphics": 3.0, "punches": 1.0, "transitions": 0.0,
        })

    def test_measured_zero_is_preserved(self) -> None:
        rates = rpl.profile_rates(profile())
        self.assertEqual(rates["punches"], 0.0)

    def test_missing_metrics_are_tolerated(self) -> None:
        value = profile()
        value["mechanics"] = {}
        verdict = rpl.lint(plan(), value, EXPECTED)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["warnings"], [])
        self.assertTrue(all(v is None for v in verdict["metrics"]["referenceRatesPerMin"].values()))

    def test_transition_classes_supply_fallback_rate(self) -> None:
        rates = rpl.profile_rates(profile())
        self.assertEqual(rates["transitions"], 2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""edit_scope tests — operator scope + per-lane directive resolution."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
import edit_scope as es
import operator_intent_contract as intent_contract
import render as renderer


class ScopeLadderTests(unittest.TestCase):
    def test_trim_activates_nothing(self) -> None:
        lanes = es.resolve_lanes({"scope": "trim"})
        self.assertTrue(all(v == "off" for v in lanes.values()), lanes)

    def test_full_activates_every_lane(self) -> None:
        lanes = es.resolve_lanes({"scope": "full"})
        self.assertTrue(all(v == "auto" for v in lanes.values()), lanes)

    def test_produced_includes_broll_from_pool(self) -> None:
        # produced engages with AVAILABLE assets incl. b-roll from the pool; full
        # adds generation of MISSING assets (same emit lanes today).
        lanes = es.resolve_lanes({"scope": "produced"})
        self.assertEqual(lanes["graphics"], "auto")
        self.assertEqual(lanes["credibility"], "auto")
        self.assertEqual(lanes["broll"], "auto")
        self.assertEqual(es.resolve_lanes({"scope": "full"}), lanes)

    def test_light_is_motion_plus_captions_only(self) -> None:
        lanes = es.resolve_lanes({"scope": "light"})
        self.assertEqual(lanes["motion"], "auto")
        self.assertEqual(lanes["captions"], "auto")
        self.assertEqual(lanes["graphics"], "off")


class BackCompatTests(unittest.TestCase):
    def test_treatment_maps_to_scope(self) -> None:
        self.assertEqual(es.resolve_scope({"treatment": "clean-cut"}), "trim")
        self.assertEqual(es.resolve_scope({"treatment": "produced"}), "produced")

    def test_default_is_produced(self) -> None:
        self.assertEqual(es.resolve_scope({}), "produced")
        self.assertEqual(es.resolve_scope(None), "produced")


class DirectiveOverrideTests(unittest.TestCase):
    def test_operator_waives_a_lane_in_full(self) -> None:
        # "full, but no b-roll — I got it": broll is off, everything else stays on.
        lanes = es.resolve_lanes({"scope": "full", "lanes": {"broll": "off"}})
        self.assertEqual(lanes["broll"], "off")
        self.assertEqual(lanes["graphics"], "auto")

    def test_operator_supplied_assets_pass_through(self) -> None:
        lanes = es.resolve_lanes({"scope": "full", "lanes": {"broll": ["clip-a", "clip-b"]}})
        self.assertEqual(lanes["broll"], ["clip-a", "clip-b"])

    def test_lane_required_only_when_auto(self) -> None:
        # The contract keys on lane_required: auto -> owed; off/operator/assets -> discharged.
        t = {"scope": "full", "lanes": {"broll": "off", "graphics": ["asset-x"],
                                        "credibility": "operator"}}
        self.assertTrue(es.lane_required(t, "motion"))         # auto -> system owes it
        self.assertFalse(es.lane_required(t, "broll"))         # waived
        self.assertFalse(es.lane_required(t, "graphics"))      # operator assets
        self.assertFalse(es.lane_required(t, "credibility"))   # operator supplies

    def test_malformed_directives_raise(self) -> None:
        self.assertRaises(ValueError, es.resolve_scope, {"scope": "trm"})      # typo
        self.assertRaises(ValueError, es.resolve_lanes, {"lanes": {"grafix": "off"}})
        self.assertRaises(ValueError, es.resolve_lanes, {"lanes": {"graphics": "yes"}})
        self.assertRaises(ValueError, es.resolve_lanes, {"lanes": {"motion": ["x"]}})
        self.assertRaises(ValueError, es.resolve_lanes, {"lanes": {"broll": []}})

    def test_auto_directive_cannot_force_a_lane_off_scope(self) -> None:
        # "trim" excludes graphics; asking auto does not resurrect it.
        lanes = es.resolve_lanes({"scope": "trim", "lanes": {"graphics": "auto"}})
        self.assertEqual(lanes["graphics"], "off")


class CaptionDeliveryScopeTests(unittest.TestCase):
    """The intent gate must see the caption burn the renderer will execute."""

    def _plan(self, mode: str) -> dict:
        """Return a minimal trim plan whose caption lane is disabled."""
        return {"target": {"mode": mode, "scope": "trim", "lanes": {}}}

    def test_omitted_short_burn_is_rejected_for_trim(self) -> None:
        """An implicit short default cannot hide a caption burn from intent."""
        plan = self._plan("short")
        verdict = intent_contract.evaluate(plan, plan["target"])
        self.assertFalse(verdict["ok"])
        self.assertTrue(verdict["metrics"]["laneEvidence"]["captions"])
        ctx = SimpleNamespace(plan=plan)
        with patch.object(renderer, "corrected_caption_words", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "burn is on"):
                renderer.captions_stage.__wrapped__(ctx, None)

    def test_explicit_off_skips_caption_work_and_passes_trim(self) -> None:
        """A no-captions request reaches neither compilation nor burn work."""
        plan = self._plan("short")
        plan["captions"] = {"burn": False}
        self.assertTrue(intent_contract.evaluate(plan, plan["target"])["ok"])
        with patch.object(renderer, "corrected_caption_words") as words:
            self.assertIsNone(renderer.captions_stage.__wrapped__(
                SimpleNamespace(plan=plan), None))
        words.assert_not_called()

    def test_longform_burn_cannot_bypass_disabled_lane(self) -> None:
        """Sidecar policy does not excuse an explicitly requested pixel burn."""
        plan = self._plan("longform")
        self.assertTrue(intent_contract.evaluate(plan, plan["target"])["ok"])
        plan["captions"] = {"burn": True}
        verdict = intent_contract.evaluate(plan, plan["target"])
        self.assertFalse(verdict["ok"])
        self.assertTrue(verdict["metrics"]["laneEvidence"]["captions"])

    def test_explicit_short_track_uses_the_same_default(self) -> None:
        """A valid track with omitted burn is visible to the disabled-lane gate."""
        plan = self._plan("short")
        plan["captionsTrack"] = {
            "schemaVersion": 1, "source": "kept-transcript",
            "defaultPolicy": "karaoke", "groups": [],
        }
        verdict = intent_contract.evaluate(plan, plan["target"])
        self.assertFalse(verdict["ok"])
        self.assertTrue(verdict["metrics"]["laneEvidence"]["captions"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

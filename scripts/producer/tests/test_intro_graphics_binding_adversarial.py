"""Adversarial regressions for transcript-bound intro graphic floors."""
from __future__ import annotations

import unittest
from unittest import mock

from _common import pl  # noqa: F401
from graphics import intro_semantic_binding as binding
from graphics import intro_semantic_contract as contract
from graphics import variety_contract as variety

KINDS = ["statement-card", "kinetic-quote-wide",
         "glass-lower-third", "whiteboard-list"]


def _beats(count: int) -> list[dict]:
    return [{"beatId": f"intro-beat-{index}", "shape": "thesis",
             "trigger": "thesis", "evidence": f"spoken beat {index}",
             "outStart": 2.0 + index * 10.0, "outEnd": 3.0 + index * 10.0,
             "compatibleKinds": KINDS, "decisionRequired": True}
            for index in range(count)]


def _plan(beats: list[dict]) -> dict:
    plan = {"target": {"mode": "longform", "scope": "produced"},
            "graphicsTrack": [], "graphicsDecisions": [], "brollTrack": []}
    for index, beat in enumerate(beats):
        kind, graphic_id = KINDS[index], f"g-valid-{index}"
        plan["graphicsTrack"].append({
            "id": graphic_id, "semanticBeatId": beat["beatId"], "kind": kind,
            "outStart": beat["outStart"], "outEnd": beat["outEnd"] + 2.0})
        plan["graphicsDecisions"].append({
            "beatId": beat["beatId"], "decision": "graphic", "kind": kind,
            "graphicId": graphic_id,
            "reason": "This graphic directly expresses the exact spoken beat.",
            "alternativesConsidered": [item for item in KINDS if item != kind][:2],
            "selectionReason": "This anatomy best fits the exact spoken structure."})
    return plan


class BindingAdversarialTests(unittest.TestCase):
    def test_omit_cannot_discharge_a_required_produced_beat(self) -> None:
        beat = _beats(1)[0]
        plan = _plan([beat])
        decision = {
            "decision": "omit",
            "reason": "A neighboring visual would otherwise carry this beat.",
        }
        self.assertIn(
            "omit cannot discharge it",
            binding.decision_error(beat, decision, plan) or "",
        )

    def test_optional_beat_may_still_be_omitted(self) -> None:
        beat = {**_beats(1)[0], "decisionRequired": False}
        plan = _plan([beat])
        decision = {
            "decision": "omit",
            "reason": "This optional opportunity does not earn another visual.",
        }
        self.assertIsNone(binding.decision_error(beat, decision, plan))

    def test_matching_broll_can_discharge_a_required_beat(self) -> None:
        beat = _beats(1)[0]
        plan = _plan([beat])
        plan["brollTrack"] = [{"outStart": 1.5, "outEnd": 4.0}]
        decision = {
            "decision": "broll",
            "reason": "This matching cutaway directly depicts the spoken beat.",
        }
        self.assertIsNone(binding.decision_error(beat, decision, plan))

    def test_bound_graphic_must_extend_to_semantic_hold_floor(self) -> None:
        beat = {**_beats(1)[0], "minimumGraphicHoldS": 1.5}
        plan = _plan([beat])
        plan["graphicsTrack"][0]["outEnd"] = beat["outStart"] + 1.45
        decision = plan["graphicsDecisions"][0]
        self.assertIn(
            "minimumGraphicHoldS 1.50s",
            binding.decision_error(beat, decision, plan) or "",
        )

    def test_broll_cannot_discharge_a_required_beat_when_lane_is_off(self) -> None:
        beat = _beats(1)[0]
        plan = _plan([beat])
        plan["target"]["lanes"] = {"broll": "off"}
        plan["brollTrack"] = [{"outStart": 1.5, "outEnd": 4.0}]
        decision = {
            "decision": "broll",
            "reason": "This matching cutaway would otherwise depict the beat.",
        }
        self.assertIn(
            "b-roll lane is off",
            binding.decision_error(beat, decision, plan) or "",
        )

    def test_checked_credibility_cannot_be_omitted(self) -> None:
        beat = {**_beats(1)[0], "shape": "credibility"}
        plan = _plan([beat])
        decision = {
            "decision": "omit",
            "reason": "The editor would otherwise choose to leave this undressed.",
        }
        self.assertIn(
            "requires a bound credibility graphic",
            binding.decision_error(beat, decision, plan) or "",
        )

    def test_duplicate_beat_shadow_invalidates_both_bindings_and_floors(self) -> None:
        beats = _beats(4)
        plan = _plan(beats)
        plan["graphicsTrack"].append({
            "id": "g-shadow", "semanticBeatId": beats[0]["beatId"],
            "kind": "widget-gauge", "outStart": 2.0, "outEnd": 5.0})
        plan["graphicsDecisions"].append({
            "beatId": beats[0]["beatId"], "decision": "graphic",
            "kind": "widget-gauge", "graphicId": "g-shadow",
            "reason": "This duplicate must never count toward a local floor.",
            "alternativesConsidered": KINDS[:2],
            "selectionReason": "This is a deliberately ambiguous shadow row."})

        self.assertNotIn(beats[0]["beatId"], binding.decision_map(plan))
        self.assertEqual(binding.validated_bound_ids(plan),
                         {"g-valid-1", "g-valid-2", "g-valid-3"})
        semantic, structural = pl.Report(), pl.Report()
        with mock.patch.object(contract, "semantic_beats", return_value=beats):
            contract.check_intro_graphics(plan, [{"word": "kept"}], 60.0,
                                          semantic)
        variety.check_variety(plan, "longform", structural, 60.0)
        self.assertTrue(any("appears 2 times" in error
                            for error in semantic.errors), semantic.errors)
        self.assertTrue(any("needs 4" in error
                            for error in semantic.errors), semantic.errors)
        self.assertTrue(any("has 3 info-bearing graphic windows" in error
                            for error in structural.errors), structural.errors)

    def test_two_beats_cannot_reduce_absolute_first_minute_floor(self) -> None:
        beats = _beats(2)
        plan = _plan(beats)
        rep = pl.Report()
        with mock.patch.object(contract, "semantic_beats", return_value=beats):
            contract.check_intro_graphics(plan, [{"word": "kept"}], 44.0, rep)
        self.assertTrue(any("insufficient transcript beats" in error
                            and "absolute 4-graphic floor" in error
                            for error in rep.errors), rep.errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)

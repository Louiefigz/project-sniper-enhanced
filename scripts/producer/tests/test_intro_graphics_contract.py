"""Transcript-bound intro graphic opportunity/decision contract tests."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from _common import gp, pl  # noqa: F401
import fingerprints as fpr
from graphics import intro_semantic_contract as isc
from graphics import variety_contract as vc

FIXTURE = Path(__file__).parent / "fixtures" / "c0679_intro_kept_transcript.json"


def _words() -> list[dict]:
    text = ("Here is the truth: three systems beat one dashboard. "
            "I built this over ten years. We use Palmier Pro versus manual "
            "editing. Finally step one ships.")
    return [{"word": token, "punctuated_word": token,
             "start": index * 0.5, "end": index * 0.5 + 0.35}
            for index, token in enumerate(text.split())]


def _base_plan() -> dict:
    return {
        "target": {"mode": "longform", "scope": "produced",
                   "graphicsStyle": "overlay-rich",
                   "graphicsStyleRationale":
                       "Dense semantic cards fit this explanatory intro."},
        "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 44.0,
                      "speed": 1.0}],
        "graphicsTrack": [], "brollTrack": [],
    }


def _c0679_words() -> tuple[list[dict], float]:
    data = json.loads(FIXTURE.read_text())
    words = []
    for segment in data["segments"]:
        tokens = segment["text"].split()
        width = (segment["outEnd"] - segment["outStart"]) / len(tokens)
        words.extend({"word": token,
                      "start": round(segment["outStart"] + index * width, 4),
                      "end": round(segment["outStart"] + (index + 1) * width, 4)}
                     for index, token in enumerate(tokens))
    return words, float(data["outputDurationS"])


def _realize_graphic(plan: dict, beat: dict, index: int) -> None:
    kind = beat["compatibleKinds"][0]
    graphic_id = f"g-{index:08d}"
    spec = {}
    if kind == "logo-card":
        spec["iconFile"] = beat["resolvedAssets"][0]
    elif kind == "icon-badge-wide":
        spec.update({f"icon{asset_index}": asset
                     for asset_index, asset in
                     enumerate(beat["resolvedAssets"], start=1)})
    plan["graphicsTrack"].append({
        "id": graphic_id, "semanticBeatId": beat["beatId"], "kind": kind,
        "outStart": beat["outStart"], "outEnd": beat["outEnd"] + 2.0,
        "spec": spec,
    })
    plan["graphicsDecisions"].append({
        "beatId": beat["beatId"], "decision": "graphic", "kind": kind,
        "graphicId": graphic_id,
        "reason": "This form directly expresses the exact spoken beat.",
        "alternativesConsidered": [item for item in beat["compatibleKinds"]
                                     if item != kind][:2],
        "selectionReason": "Its anatomy fits this exact spoken structure best.",
    })


class SemanticBeatTests(unittest.TestCase):
    def test_actual_c0679_intro_surfaces_every_real_information_shape(self) -> None:
        words, duration = _c0679_words()
        beats = isc.semantic_beats(words, duration)
        triggers = {beat["trigger"] for beat in beats}
        expected = {"audience-list", "tool-list", "promise", "maturity-stage",
                    "limitation", "credibility", "building-proof", "exact-proof"}
        self.assertEqual(expected - triggers, set(), beats)
        self.assertGreaterEqual(len(beats), 8, beats)
        tool = next(beat for beat in beats if beat["trigger"] == "tool-list")
        self.assertEqual(tool["resolvedAssets"],
                         ["openai-color.svg", "claude-color.svg",
                          "gemini-color.svg"])
        self.assertEqual(tool["compatibleKinds"][0], "icon-badge-wide")
        for trigger in ("credibility", "building-proof", "exact-proof"):
            beat = next(row for row in beats if row["trigger"] == trigger)
            self.assertNotIn("logo-card", beat["compatibleKinds"])
            self.assertNotIn("icon-badge-wide", beat["compatibleKinds"])
        self.assertTrue(all("canvas-pip-list" not in beat["compatibleKinds"]
                            for beat in beats), beats)
        self.assertTrue(all(beat["minimumGraphicHoldS"] == 1.5
                            for beat in beats), beats)

    def test_transcript_surfaces_multiple_information_shapes_and_forms(self) -> None:
        beats = isc.semantic_beats(_words(), 44.0)
        shapes = {beat["shape"] for beat in beats}
        self.assertGreaterEqual(len(beats), 4, beats)
        self.assertTrue({"comparison", "credibility", "process"} <= shapes,
                        beats)
        for beat in beats:
            self.assertTrue(beat["compatibleKinds"], beat)
            self.assertTrue(beat["beatId"].startswith("intro-"), beat)

    def test_number_painting_kinds_need_a_spoken_number_in_the_beat_window(self) -> None:
        from producer_config import MOTION
        words = _words()
        beat = next(row for row in isc.semantic_beats(words, 44.0) if row["shape"] == "comparison")
        self.assertIn("chart-story", MOTION["card_form_map"]["comparison"])
        self.assertNotIn("chart-story", beat["compatibleKinds"], beat)     # "Pro versus manual" speaks no number
        self.assertNotIn("count-up", beat["compatibleKinds"], beat)
        self.assertIn("nateherk-scoreboard", beat["compatibleKinds"], beat)
        spoken = sorted(words + [{"word": "12", "start": 10.38, "end": 10.48}], key=lambda w: w["start"])
        spoken_beat = next(row for row in isc.semantic_beats(spoken, 44.0) if row["shape"] == "comparison")
        self.assertIn("chart-story", spoken_beat["compatibleKinds"], spoken_beat)

    def test_measure_noun_is_scale_not_a_list(self) -> None:
        beats = isc.semantic_beats(_words(), 44.0)
        years = next(beat for beat in beats if "ten years" in beat["evidence"])
        self.assertEqual(years["shape"], "scale")
        self.assertIn("nateherk-scoreboard", years["compatibleKinds"])

    def test_proposal_keeps_semantic_beats_when_style_retarget_prunes_cards(self) -> None:
        plan = _base_plan()
        plan["target"]["graphicsStyle"] = "cutaway-only"
        with mock.patch.object(gp, "output_words", return_value=_words()), \
                mock.patch.object(gp, "_source_topic_boundaries", return_value=[]):
            proposal = gp.build_proposal(plan, "/unused", {"sources": []})
        self.assertGreaterEqual(len(proposal["introSemanticBeats"]), 4)
        self.assertEqual(proposal["meta"]["introSemanticBeatCount"],
                         len(proposal["introSemanticBeats"]))

    def test_overlay_rich_sequence_fallback_accepts_both_structural_lists(self) -> None:
        plan = _base_plan()
        with mock.patch.object(gp, "output_words", return_value=_words()), \
                mock.patch.object(gp, "_source_topic_boundaries", return_value=[]):
            proposal = gp.build_proposal(plan, "/unused", {"sources": []})
        self.assertGreaterEqual(proposal["meta"]["introSemanticBeatCount"], 4)


class SemanticDecisionTests(unittest.TestCase):
    def test_early_semantic_floor_matches_structural_window_growth(self) -> None:
        self.assertEqual(isc._early_graphics_floor(61.0), 5)
        self.assertEqual(isc._early_graphics_floor(126.0), 6)
        self.assertEqual(isc._early_graphics_floor(151.0), 7)
        self.assertEqual(isc._early_graphics_floor(180.0), 8)

    def test_decision_receipts_do_not_invalidate_identical_pixels(self) -> None:
        before = _base_plan()
        after = {**before, "graphicsDecisions": [{
            "beatId": "intro-proof", "decision": "omit",
            "reason": "A neighboring visual already carries this exact beat."}]}
        self.assertEqual(fpr.base_fingerprint(before), fpr.base_fingerprint(after))
        self.assertEqual(fpr.video_fingerprint(before), fpr.video_fingerprint(after))
        self.assertEqual(fpr.plan_content_hash(before), fpr.plan_content_hash(after))

    def test_plan_lint_invokes_transcript_semantic_gate(self) -> None:
        plan = _base_plan()
        plan["planVersion"] = 1
        manifest = {"sources": [{"id": "raw-1", "duration": 44.0}],
                    "broll": [], "music": []}
        errors = pl.lint(plan, manifest, _words()).errors
        self.assertTrue(any("has no persisted graphicsDecisions row" in error
                            for error in errors), errors)

    def test_missing_decisions_fail_each_beat_and_the_density_floor(self) -> None:
        plan = _base_plan()
        rep = pl.Report()
        beats = isc.semantic_beats(_words(), 44.0)
        isc.check_intro_graphics(plan, _words(), 44.0, rep)
        missing = [error for error in rep.errors
                   if "has no persisted graphicsDecisions row" in error]
        self.assertEqual(len(missing), len(beats), rep.errors)
        self.assertTrue(any("first minute" in error and "graphic decisions" in error
                            for error in rep.errors), rep.errors)

    def test_every_c0679_beat_is_realized_when_broll_is_off(self) -> None:
        words, duration = _c0679_words()
        plan = _base_plan()
        plan["target"]["lanes"] = {"broll": "off"}
        plan["cutTrack"][0]["end"] = duration
        beats = isc.semantic_beats(words, duration)
        plan["graphicsDecisions"] = []
        for index, beat in enumerate(beats):
            _realize_graphic(plan, beat, index)
        rep = pl.Report()
        isc.check_intro_graphics(plan, words, duration, rep)
        self.assertEqual(len(beats), 8)
        self.assertEqual(len(plan["graphicsTrack"]), 8)
        self.assertTrue(all(row["decision"] == "graphic"
                            for row in plan["graphicsDecisions"]))
        self.assertEqual(rep.errors, [])

    def test_fourth_unbound_filler_does_not_satisfy_semantic_floor(self) -> None:
        plan = _base_plan()
        beats = isc.semantic_beats(_words(), 44.0)
        plan["graphicsDecisions"] = []
        for index, beat in enumerate(beats):
            if index < 3:
                kind = beat["compatibleKinds"][0]
                graphic_id = f"g-{index:08d}"
                plan["graphicsTrack"].append({
                    "id": graphic_id, "semanticBeatId": beat["beatId"],
                    "kind": kind, "outStart": beat["outStart"],
                    "outEnd": beat["outEnd"] + 2.0})
                decision = {
                    "beatId": beat["beatId"], "decision": "graphic",
                    "kind": kind, "graphicId": graphic_id,
                    "reason": "This realizes the spoken beat.",
                    "alternativesConsidered": [item for item in
                        beat["compatibleKinds"] if item != kind][:2],
                    "selectionReason":
                        "Its anatomy fits this exact spoken structure best."}
            else:
                decision = {"beatId": beat["beatId"], "decision": "omit",
                            "reason": "A nearby visual carries this spoken beat."}
            plan["graphicsDecisions"].append(decision)
        plan["graphicsTrack"].append({"kind": "statement-card",
                                      "outStart": 30.0, "outEnd": 33.0})
        rep = pl.Report()
        isc.check_intro_graphics(plan, _words(), 44.0, rep)
        self.assertTrue(any("only 3 uniquely bound graphic decisions (needs 4)"
                            in error
                            for error in rep.errors), rep.errors)

    def test_semantically_incompatible_kind_fails_even_if_a_card_exists(self) -> None:
        plan = _base_plan()
        beat = next(row for row in isc.semantic_beats(_words(), 44.0)
                    if row["shape"] == "comparison")
        plan["graphicsTrack"] = [{"id": "g-wrong111",
                                  "semanticBeatId": beat["beatId"],
                                  "kind": "statement-card",
                                  "outStart": beat["outStart"],
                                  "outEnd": beat["outEnd"] + 2.0}]
        plan["graphicsDecisions"] = [{
            "beatId": beat["beatId"], "decision": "graphic",
            "kind": "statement-card", "graphicId": "g-wrong111",
            "reason": "This deliberately records the wrong form for the test."}]
        rep = pl.Report()
        isc.check_intro_graphics(plan, _words(), 44.0, rep)
        self.assertTrue(any("outside compatible forms" in error
                            for error in rep.errors), rep.errors)

    def test_first_compatible_kind_without_selection_receipt_fails(self) -> None:
        plan = _base_plan()
        beat = isc.semantic_beats(_words(), 44.0)[0]
        kind = beat["compatibleKinds"][0]
        plan["graphicsTrack"] = [{"id": "g-first111",
                                  "semanticBeatId": beat["beatId"],
                                  "kind": kind, "outStart": beat["outStart"],
                                  "outEnd": beat["outEnd"] + 2.0}]
        plan["graphicsDecisions"] = [{
            "beatId": beat["beatId"], "decision": "graphic", "kind": kind,
            "graphicId": "g-first111",
            "reason": "The first catalog entry was chosen without review."}]
        rep = pl.Report()
        isc.check_intro_graphics(plan, _words(), 44.0, rep)
        self.assertTrue(any("alternativesConsidered" in error
                            for error in rep.errors), rep.errors)

    def test_shared_window_plus_filler_fails_semantic_and_structural_floors(self) -> None:
        words, duration = _c0679_words()
        beats = isc.semantic_beats(words, duration)
        plan = _base_plan()
        plan["cutTrack"][0]["end"] = duration
        plan["graphicsDecisions"] = []
        shared = next(beat for beat in beats if beat["trigger"] == "audience-list")
        shared_kind = "glass-rail"
        plan["graphicsTrack"] = [{
            "id": "g-shared11", "semanticBeatId": shared["beatId"],
            "kind": shared_kind, "outStart": 0.0, "outEnd": 12.0}]
        for index, beat in enumerate(beats):
            if index < 2:
                kind, graphic_id = shared_kind, "g-shared11"
            elif index < 4:
                kind, graphic_id = beat["compatibleKinds"][0], f"g-real{index:04d}"
                plan["graphicsTrack"].append({
                    "id": graphic_id, "semanticBeatId": beat["beatId"],
                    "kind": kind, "outStart": beat["outStart"],
                    "outEnd": beat["outEnd"] + 1.0})
            else:
                plan["graphicsDecisions"].append({
                    "beatId": beat["beatId"], "decision": "omit",
                    "reason": "A stronger neighboring visual already carries this beat."})
                continue
            plan["graphicsDecisions"].append({
                "beatId": beat["beatId"], "decision": "graphic",
                "kind": kind, "graphicId": graphic_id,
                "reason": "This form directly expresses the exact spoken beat.",
                "alternativesConsidered": [item for item in beat["compatibleKinds"]
                                            if item != kind][:2],
                "selectionReason": "This anatomy fits the exact spoken structure best."})
        plan["graphicsTrack"].append({
            "id": "g-filler11", "kind": "kinetic-quote-wide",
            "outStart": 30.0, "outEnd": 33.0})
        semantic, structural = pl.Report(), pl.Report()
        isc.check_intro_graphics(plan, words, duration, semantic)
        vc.check_variety(plan, "longform", structural, duration)
        self.assertTrue(any("is reused by semantic beats" in error
                            for error in semantic.errors), semantic.errors)
        self.assertTrue(any("uniquely bound graphic decisions" in error
                            for error in semantic.errors), semantic.errors)
        self.assertTrue(any("needs at least 4 windows" in error
                            for error in structural.errors), structural.errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)

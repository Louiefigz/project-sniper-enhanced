"""Actual catalog routing and isolated transcript-decision contract regressions."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from _common import gp, pl  # noqa: F401
import fingerprints as fpr
from graphics import intro_semantic_contract as isc
from graphics.intro_semantic_binding import (
    decision_error, decision_map, density_error, reuse_errors,
)
from graphics.visual_source_policy import integrated_kinds

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
                   "graphicsStyle": "catalog-first"},
        "cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 44, "speed": 1}],
        "graphicsTrack": [], "brollTrack": [],
    }


def _c0679_words() -> tuple[list[dict], float]:
    data = json.loads(FIXTURE.read_text())
    words = []
    for segment in data["segments"]:
        tokens = segment["text"].split()
        width = (segment["outEnd"] - segment["outStart"]) / len(tokens)
        words.extend({"word": token,
                      "start": segment["outStart"] + index * width,
                      "end": segment["outStart"] + (index + 1) * width}
                     for index, token in enumerate(tokens))
    return words, float(data["outputDurationS"])


def _binding_fixture() -> tuple[dict, list[dict]]:
    """Inert decision DTOs; no media, automatic selection or approval claim."""
    plan = _base_plan()
    beats = [{"beatId": f"test-beat-{i}", "shape": "evidence",
              "compatibleKinds": ["ui-focus-zoom"], "outStart": i * 5,
              "outEnd": i * 5 + 2, "minimumGraphicHoldS": 1.5,
              "decisionRequired": True} for i in range(4)]
    plan["graphicsDecisions"] = []
    for index, beat in enumerate(beats):
        identity = f"g-{index:08d}"
        plan["graphicsTrack"].append({
            "id": identity, "semanticBeatId": beat["beatId"],
            "kind": "ui-focus-zoom", "outStart": beat["outStart"],
            "outEnd": beat["outEnd"]})
        plan["graphicsDecisions"].append({
            "beatId": beat["beatId"], "decision": "graphic",
            "kind": "ui-focus-zoom", "graphicId": identity,
            "reason": "TEST a bound screen demonstrates the spoken detail.",
            "alternativesConsidered": [],
            "selectionReason": "TEST this screen source demonstrates this exact detail."})
    return plan, beats


class SemanticBeatTests(unittest.TestCase):
    def test_actual_intro_preserves_eight_unmapped_native_obligations(self) -> None:
        words, duration = _c0679_words()
        beats = isc.semantic_beats(words, duration)
        expected = {"audience-list", "tool-list", "promise", "maturity-stage",
                    "limitation", "credibility", "building-proof", "exact-proof"}
        self.assertEqual({row["trigger"] for row in beats}, expected)
        self.assertEqual(len(beats), 8)
        tool = next(row for row in beats if row["trigger"] == "tool-list")
        self.assertEqual(tool["resolvedAssets"],
                         ["openai-color.svg", "claude-color.svg", "gemini-color.svg"])
        self.assertTrue(all(row["decisionRequired"] and row["nativeCatalogRequired"] for row in beats))
        self.assertTrue(all(row["compatibleKinds"] == [] and row["preferredKind"] is None for row in beats))
        self.assertTrue(all(row["minimumGraphicHoldS"] == 1.5 for row in beats))

    def test_detected_shapes_never_gain_house_template_fallbacks(self) -> None:
        beats = isc.semantic_beats(_words(), 44)
        self.assertTrue({"comparison", "credibility", "process"} <= {row["shape"] for row in beats})
        for row in beats:
            self.assertTrue(set(row["compatibleKinds"]) <= integrated_kinds())
            self.assertEqual(row["nativeCatalogRequired"], not bool(row["compatibleKinds"]))
            self.assertTrue(row["beatId"].startswith("intro-"))

    def test_numeric_compatibility_requires_spoken_number(self) -> None:
        row = next(row for row in isc.semantic_beats(_words(), 44) if row["shape"] == "comparison")
        forms = ["chart-story", "count-up", "ui-focus-zoom"]
        self.assertEqual(isc._speakable_forms(forms, _words(), row), ["ui-focus-zoom"])
        spoken = sorted(_words() + [{"word": "12", "start": 10.38, "end": 10.48}], key=lambda word: word["start"])
        self.assertEqual(isc._speakable_forms(forms, spoken, row), forms)

    def test_measure_noun_keeps_scale_intent_without_old_scoreboard(self) -> None:
        row = next(row for row in isc.semantic_beats(_words(), 44) if "ten years" in row["evidence"])
        self.assertEqual(row["shape"], "scale")
        self.assertNotIn("module-scoreboard", row["compatibleKinds"])

    def test_retired_style_rejects_before_planning(self) -> None:
        for style in ("cutaway-only", "overlay-rich", "module-editorial-v1"):
            plan = _base_plan()
            plan["target"]["graphicsStyle"] = style
            with self.subTest(style=style), self.assertRaisesRegex(ValueError, "retired"):
                gp.build_proposal(plan, "/unused", {"sources": []})

    def test_catalog_proposal_preserves_unassignable_beats(self) -> None:
        with mock.patch.object(gp, "output_words", return_value=_words()), \
                mock.patch.object(gp, "_source_topic_boundaries", return_value=[]):
            proposal = gp.build_proposal(_base_plan(), "/unused", {"sources": []})
        self.assertGreaterEqual(proposal["meta"]["introSemanticBeatCount"], 4)
        self.assertTrue(proposal["formAllocation"]["unassignableBeatIds"])


class SemanticDecisionTests(unittest.TestCase):
    def test_historical_density_calculation_is_preserved(self) -> None:
        self.assertEqual([isc._early_graphics_floor(end) for end in (61, 126, 151, 180)], [5, 6, 7, 8])

    def test_decisions_do_not_change_identical_pixels(self) -> None:
        before = _base_plan()
        after = {**before, "graphicsDecisions": [{"beatId": "intro-proof", "decision": "omit", "reason": "TEST neighboring visual"}]}
        for fingerprint in (fpr.base_fingerprint, fpr.video_fingerprint, fpr.plan_content_hash):
            self.assertEqual(fingerprint(before), fingerprint(after))

    def test_plan_lint_requires_decisions_for_actual_beats(self) -> None:
        plan = {**_base_plan(), "planVersion": 1}
        manifest = {"sources": [{"id": "raw-1", "duration": 44}], "broll": [], "music": []}
        errors = pl.lint(plan, manifest, _words()).errors
        self.assertTrue(any("has no persisted graphicsDecisions row" in error for error in errors), errors)

    def test_catalog_decisions_have_no_house_count_quota(self) -> None:
        rep = pl.Report()
        isc.check_intro_graphics(_base_plan(), _words(), 44, rep)
        beats = isc.semantic_beats(_words(), 44)
        self.assertEqual(len(rep.errors), len(beats), rep.errors)
        self.assertTrue(all("has no persisted graphicsDecisions row" in error for error in rep.errors))

    def test_real_obligation_cannot_be_filled_by_retired_kind(self) -> None:
        plan, _ = _binding_fixture()
        words, duration = _c0679_words()
        beat = isc.semantic_beats(words, duration)[0]
        decision = {**plan["graphicsDecisions"][0], "kind": "glass-rail"}
        self.assertIn("outside compatible forms", decision_error(beat, decision, plan))

    def test_bound_decisions_validate_and_missing_selection_receipt_rejects(self) -> None:
        plan, beats = _binding_fixture()
        for beat, decision in zip(beats, plan["graphicsDecisions"]):
            self.assertIsNone(decision_error(beat, decision, plan))
        decision = copy.deepcopy(plan["graphicsDecisions"][0])
        decision.pop("alternativesConsidered")
        self.assertIn("alternativesConsidered", decision_error(beats[0], decision, plan))

    def test_historical_floor_ignores_unbound_filler(self) -> None:
        plan, beats = _binding_fixture()
        plan["graphicsDecisions"].pop()
        plan["graphicsTrack"].append({"kind": "line-swap", "outStart": 30, "outEnd": 33})
        error = density_error(beats, decision_map(plan), plan, (44, 4, "first minute"))
        self.assertIn("only 3 uniquely bound graphic decisions (needs 4)", error)

    def test_shared_graphic_cannot_discharge_multiple_beats(self) -> None:
        plan, beats = _binding_fixture()
        plan["graphicsDecisions"][1]["graphicId"] = plan["graphicsDecisions"][0]["graphicId"]
        self.assertTrue(any("is reused by semantic beats" in error for error in reuse_errors(plan)))
        self.assertIn("only 2 uniquely bound", density_error(beats, decision_map(plan), plan, (44, 4, "first minute")))


if __name__ == "__main__":
    unittest.main(verbosity=2)

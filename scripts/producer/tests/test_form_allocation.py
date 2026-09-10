"""Global semantic-form allocation must maximize legal visual variety."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _common import gp  # noqa: F401
from graphics.form_allocation import (
    GATE_ILLEGAL_KINDS,
    assess_kind_reuse,
    assess_profile_form_reuse,
    build_form_allocation,
    is_gate_executable_kind,
)
from graphics.intro_semantic_contract import semantic_beats
from planner import graphics_planner_items as planner_items

FIXTURE = Path(__file__).parent / "fixtures" / "c0679_intro_kept_transcript.json"


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


def _beat(beat_id: str, forms: list[str], start: float = 0.0) -> dict:
    return {"beatId": beat_id, "compatibleKinds": forms,
            "outStart": start, "decisionRequired": True}


class FormAllocationTests(unittest.TestCase):
    def test_c0679_has_a_legal_eight_form_perfect_matching(self) -> None:
        words, duration = _c0679_words()
        beats = semantic_beats(words, duration)
        preferred = {row["beatId"]: row["preferredKind"] for row in beats}
        allocation = build_form_allocation(beats, preferred)
        compatible = {row["beatId"]: set(row["compatibleKinds"])
                      for row in beats}
        assigned = allocation["recommendedAssignment"]
        by_trigger = {row["trigger"]: row for row in beats}
        recommended = {row["beatId"]: row["kind"] for row in assigned}
        self.assertEqual(allocation["beatCount"], 8)
        self.assertEqual(allocation["maximumFeasibleDistinctKinds"], 8)
        self.assertEqual(len({row["kind"] for row in assigned}), 8)
        self.assertTrue(all(row["kind"] in compatible[row["beatId"]]
                            for row in assigned), assigned)
        self.assertTrue(all(is_gate_executable_kind(row["kind"])
                            for row in assigned), assigned)
        self.assertTrue(all(not GATE_ILLEGAL_KINDS.intersection(kinds)
                            for kinds in compatible.values()), compatible)
        tool = by_trigger["tool-list"]
        self.assertEqual(tool["preferredKind"], "icon-badge-wide")
        self.assertEqual(recommended[tool["beatId"]], "icon-badge-wide")

    def test_gate_illegal_forms_do_not_inflate_the_matching(self) -> None:
        beats = [_beat("one", ["canvas-pip-list", "statement-card"]),
                 _beat("two", ["canvas-pip-list"])]
        allocation = build_form_allocation(beats)
        self.assertEqual(allocation["maximumFeasibleDistinctKinds"], 1)
        self.assertEqual(allocation["recommendedAssignment"], [
            {"beatId": "one", "kind": "statement-card"},
        ])
        self.assertEqual(allocation["unassignableBeatIds"], ["two"])

    def test_overlay_rich_planner_never_emits_blocked_pip_form(self) -> None:
        text = "We use a camera, a microphone, a light, a stand, and a monitor."
        words = [{"word": token, "start": index * 0.4,
                  "end": index * 0.4 + 0.3}
                 for index, token in enumerate(text.split())]
        ctx = SimpleNamespace(words=words, mode="longform", out_dur=20.0,
                              state_fn=lambda _at: ("talking-head", None))
        candidates = planner_items.pip_aware_maps(ctx)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["kind"], "whiteboard-list")
        self.assertNotIn("needsPip", candidates[0])
        self.assertTrue(is_gate_executable_kind(candidates[0]["kind"]))

    def test_catalog_order_does_not_change_the_assignment(self) -> None:
        beats = [_beat("beat-b", ["form-c", "form-a"], 2.0),
                 _beat("beat-a", ["form-b", "form-a"], 1.0),
                 _beat("beat-c", ["form-c", "form-b"], 3.0)]
        permuted = [{**row, "compatibleKinds": list(reversed(
            row["compatibleKinds"]))} for row in reversed(beats)]
        with mock.patch("graphics.form_allocation.is_aspect_legal_kind",
                        return_value=True):
            self.assertEqual(build_form_allocation(beats),
                             build_form_allocation(permuted))

    def test_unavoidable_reuse_passes_without_a_fake_witness(self) -> None:
        beats = [_beat("one", ["form-a"]), _beat("two", ["form-a"]),
                 _beat("three", ["form-b"])]
        decisions = [{"beatId": "one", "decision": "graphic", "kind": "form-a"},
                     {"beatId": "two", "decision": "graphic", "kind": "form-a"},
                     {"beatId": "three", "decision": "graphic", "kind": "form-b"}]
        with mock.patch("graphics.form_allocation.is_aspect_legal_kind",
                        return_value=True):
            result = assess_kind_reuse(beats, decisions)
        self.assertFalse(result["avoidableReuse"], result)
        self.assertEqual(result["maximumFeasibleDistinctKinds"], 2)
        self.assertEqual(result["replacementWitnesses"], [])

    def test_avoidable_reuse_returns_only_compatible_replacements(self) -> None:
        beats = [_beat("one", ["form-a", "form-b"]),
                 _beat("two", ["form-b", "form-a"])]
        decisions = [{"beatId": row["beatId"], "decision": "graphic",
                      "kind": "form-a"} for row in beats]
        with mock.patch("graphics.form_allocation.is_aspect_legal_kind",
                        return_value=True):
            result = assess_kind_reuse(beats, decisions)
        compatible = {row["beatId"]: set(row["compatibleKinds"])
                      for row in beats}
        self.assertTrue(result["avoidableReuse"], result)
        self.assertEqual(result["maximumFeasibleDistinctKinds"], 2)
        self.assertTrue(result["replacementWitnesses"], result)
        self.assertTrue(all(row["replacementKind"] in compatible[row["beatId"]]
                            for row in result["replacementWitnesses"]))

    def test_profile_variety_counts_forms_sharing_one_renderer(self) -> None:
        beats = [{"beatId": beat_id, "outStart": index * 5.0,
                  "compatibleForms": ["step-sequence", "resolved-checklist"]}
                 for index, beat_id in enumerate(("one", "two"))]
        decisions = [{"beatId": row["beatId"], "decision": "graphic",
                      "kind": "nateherk-rail",
                      "informationForm": "step-sequence"} for row in beats]
        result = assess_profile_form_reuse(
            beats, decisions, "nateherk-editorial-v1")
        self.assertTrue(result["avoidableReuse"], result)
        self.assertEqual(result["maximumFeasibleDistinctForms"], 2)
        self.assertTrue(result["replacementWitnesses"], result)

    def test_proposal_exposes_the_global_assignment(self) -> None:
        beats = [_beat("one", ["statement-card", "glass-rail"]),
                 _beat("two", ["glass-rail", "statement-card"], 2.0)]
        beats[0]["preferredKind"] = "glass-rail"
        beats[1]["preferredKind"] = "statement-card"
        plan = {"target": {"mode": "longform", "scope": "produced",
                           "graphicsStyle": "overlay-rich",
                           "graphicsStyleRationale":
                               "Transcript-dense beats need varied visual forms."},
                "cutTrack": [{"sourceId": "raw", "start": 0.0, "end": 10.0}]}
        with mock.patch.object(gp, "output_words", return_value=[]), \
                mock.patch.object(gp, "semantic_beats", return_value=beats), \
                mock.patch.object(gp, "_source_topic_boundaries", return_value=[]):
            proposal = gp.build_proposal(plan, "/unused", {"sources": []})
        self.assertEqual(proposal["formAllocation"]
                         ["maximumFeasibleDistinctKinds"], 2)
        self.assertEqual(proposal["meta"]["maximumFeasibleDistinctKinds"], 2)
        self.assertEqual(proposal["formAllocation"]["recommendedAssignment"], [
            {"beatId": "one", "kind": "glass-rail"},
            {"beatId": "two", "kind": "statement-card"},
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)

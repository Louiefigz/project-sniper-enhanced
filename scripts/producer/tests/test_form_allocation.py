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
    def test_c0679_preserves_all_beats_requiring_native_catalog_selection(self) -> None:
        words, duration = _c0679_words()
        beats = semantic_beats(words, duration)
        allocation = build_form_allocation(beats)
        self.assertEqual(len(beats), 8)
        self.assertTrue(all(row["decisionRequired"] and row["nativeCatalogRequired"] for row in beats))
        self.assertEqual(allocation["recommendedAssignment"], [])
        self.assertEqual(allocation["maximumFeasibleDistinctKinds"], 0)
        self.assertEqual(set(allocation["unassignableBeatIds"]), {row["beatId"] for row in beats})

    def test_gate_illegal_forms_do_not_inflate_the_matching(self) -> None:
        beats = [_beat("one", ["canvas-pip-list", "chart-story"]),
                 _beat("two", ["canvas-pip-list"])]
        allocation = build_form_allocation(beats)
        self.assertEqual(allocation["maximumFeasibleDistinctKinds"], 1)
        self.assertEqual(allocation["recommendedAssignment"], [
            {"beatId": "one", "kind": "chart-story"},
        ])
        self.assertEqual(allocation["unassignableBeatIds"], ["two"])

    def test_old_list_planner_does_not_substitute_a_house_template(self) -> None:
        text = "We use a camera, a microphone, a light, a stand, and a monitor."
        words = [{"word": token, "start": index * 0.4, "end": index * 0.4 + 0.3}
                 for index, token in enumerate(text.split())]
        ctx = SimpleNamespace(words=words, mode="longform", out_dur=20.0,
                              state_fn=lambda _at: ("talking-head", None))
        with self.assertRaisesRegex(ValueError, "retired"):
            planner_items.pip_aware_maps(ctx)

    def test_catalog_order_does_not_change_the_assignment(self) -> None:
        beats = [_beat("beat-b", ["line-swap", "chart-story"], 2.0),
                 _beat("beat-a", ["ui-focus-zoom", "chart-story"], 1.0),
                 _beat("beat-c", ["line-swap", "ui-focus-zoom"], 3.0)]
        permuted = [{**row, "compatibleKinds": list(reversed(
            row["compatibleKinds"]))} for row in reversed(beats)]
        with mock.patch("graphics.form_allocation.is_aspect_legal_kind",
                        return_value=True):
            self.assertEqual(build_form_allocation(beats),
                             build_form_allocation(permuted))

    def test_unavoidable_reuse_passes_without_a_fake_witness(self) -> None:
        beats = [_beat("one", ["chart-story"]), _beat("two", ["chart-story"]),
                 _beat("three", ["ui-focus-zoom"])]
        decisions = [{"beatId": "one", "decision": "graphic", "kind": "chart-story"},
                     {"beatId": "two", "decision": "graphic", "kind": "chart-story"},
                     {"beatId": "three", "decision": "graphic", "kind": "ui-focus-zoom"}]
        with mock.patch("graphics.form_allocation.is_aspect_legal_kind",
                        return_value=True):
            result = assess_kind_reuse(beats, decisions)
        self.assertFalse(result["avoidableReuse"], result)
        self.assertEqual(result["maximumFeasibleDistinctKinds"], 2)
        self.assertEqual(result["replacementWitnesses"], [])

    def test_avoidable_reuse_returns_only_compatible_replacements(self) -> None:
        beats = [_beat("one", ["chart-story", "ui-focus-zoom"]),
                 _beat("two", ["ui-focus-zoom", "chart-story"])]
        decisions = [{"beatId": row["beatId"], "decision": "graphic",
                      "kind": "chart-story"} for row in beats]
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

    def test_profile_variety_cannot_reenable_retired_house_forms(self) -> None:
        with self.assertRaisesRegex(ValueError, "retired"):
            assess_profile_form_reuse([], [], "module-editorial-v1")

    def test_proposal_exposes_the_global_assignment(self) -> None:
        beats = [_beat("one", ["chart-story", "ui-focus-zoom"]),
                 _beat("two", ["ui-focus-zoom", "chart-story"], 2.0)]
        beats[0]["preferredKind"] = "ui-focus-zoom"
        beats[1]["preferredKind"] = "chart-story"
        plan = {"target": {"mode": "longform", "scope": "produced",
                           "graphicsStyle": "catalog-first",
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
            {"beatId": "one", "kind": "ui-focus-zoom"},
            {"beatId": "two", "kind": "chart-story"},
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)

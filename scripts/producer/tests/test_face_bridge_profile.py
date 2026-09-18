#!/usr/bin/env python3
"""Executable contracts for the face-bridge editorial profile."""
from __future__ import annotations

import unittest

from _common import *  # noqa: F401,F403
from graphics.form_allocation import build_form_allocation
from graphics.intro_semantic_binding import decision_error
from graphics.style_profile_contract import (_renderer_errors,
                                             check_style_profile)
from graphics.style_profiles import (FACE_BRIDGE_PROFILE, form_contract,
                                     forms_for_shape)
from graphics.variety_contract import check_variety
from planner import graphics_planner_longform as longform
from planner import graphics_planner_face_bridge as face_bridge
from graphics_style_advisor import recommend_style


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)


def _spec(information_form: str) -> dict:
    values = {
        "status-queue": {"eyebrow": "INPUT", "headlineLines": "One prompt.",
                         "rows": "PROMPT~RECEIVED~result",
                         "moduleLands": [0.2, 0.9]},
        "comparison-bars": {"eyebrow": "SCORES",
                            "headlineLines": "The numbers moved.",
                            "heroLabel": "NEW", "heroValue": "91.9",
                            "heroPct": "92", "compareLabel": "OLD",
                            "compareValue": "85.6", "comparePct": "86",
                            "deltaChip": "+6.3", "evidenceSource": "REPORT",
                            "moduleLands": [0.2, 0.9, 1.8]},
        "step-sequence": {"eyebrow": "PROCESS",
                          "headlineLines": "Every handoff.",
                          "rows": "01~Research~SOURCE|02~Build~DONE",
                          "moduleLands": [0.2, 0.9, 1.6]},
        "hero-scoreboard": {"eyebrow": "RESULT", "heroValue": "97%",
                            "heroLabel": "POINTS", "tiles": "7~WINS",
                            "limitText": "One local check.",
                            "moduleLands": [0.2, 0.9, 1.8]},
    }
    contract = form_contract(FACE_BRIDGE_PROFILE, information_form) or {}
    return {**values[information_form], **contract.get("fixedSpec", {})}


def _entry(index: int, information_form: str, start: float, end: float) -> dict:
    contract = form_contract(FACE_BRIDGE_PROFILE, information_form) or {}
    chassis = contract["chassis"]
    return {"id": f"g-{index}", "semanticBeatId": f"b-{index}",
            "informationForm": information_form, "chassis": chassis,
            "kind": contract["kind"], "outStart": start, "outEnd": end,
            "anchor": "beside-face" if chassis == "cream" else "own-screen",
            "spec": _spec(information_form)}


def _plan() -> dict:
    forms = ["status-queue", "comparison-bars", "step-sequence",
             "hero-scoreboard"]
    spans = [(13.5, 24.0), (24.0, 36.0), (36.0, 48.0), (48.0, 60.0)]
    graphics = [_entry(i, form, *spans[i]) for i, form in enumerate(forms)]
    decisions = [{"beatId": row["semanticBeatId"], "decision": "graphic",
                  "graphicId": row["id"], "kind": row["kind"],
                  "informationForm": row["informationForm"],
                  "chassis": row["chassis"], "reason": "Transcript earns this form"}
                 for row in graphics]
    return {"target": {"mode": "longform", "scope": "produced",
                       "graphicsStyle": "face-bridge",
                       "graphicsStyleRationale": "Evidence-dense presenter bridge",
                       "visualProfile": FACE_BRIDGE_PROFILE},
            "graphicsTrack": graphics, "graphicsDecisions": decisions,
            "punchIns": []}


class FaceBridgeTargetTests(unittest.TestCase):
    def test_face_bridge_requires_a_typed_profile(self) -> None:
        plan = {"target": {"mode": "longform", "scope": "produced",
                           "graphicsStyle": "face-bridge",
                           "graphicsStyleRationale": "Continuous presenter"}}
        with self.assertRaisesRegex(ValueError, "visualProfile"):
            longform.resolve_style(None, plan)

    def test_typed_profile_resolves(self) -> None:
        self.assertEqual(longform.resolve_style(None, _plan()), "face-bridge")

    def test_advisor_selects_profile_from_density_shape_and_face(self) -> None:
        plan = _plan()
        plan["faceBBoxNorm"] = [0.45, 0.2, 0.15, 0.3]
        shapes = ["process", "comparison", "evidence", "list"] * 2
        advice = recommend_style(plan, [{"shape": shape} for shape in shapes])
        fields = advice["recommendedTargetFields"]
        self.assertEqual(fields["graphicsStyle"], "face-bridge")
        self.assertEqual(fields["visualProfile"], FACE_BRIDGE_PROFILE)

    def test_advisor_uses_overlay_without_presenter_tracking(self) -> None:
        shapes = ["process", "comparison", "evidence"] * 2
        advice = recommend_style(_plan(), [{"shape": shape} for shape in shapes])
        self.assertEqual(advice["recommendedTargetFields"]["graphicsStyle"],
                         "overlay-rich")


class FaceBridgeAllocationTests(unittest.TestCase):
    def test_context_specific_shapes_select_distinct_renderers(self) -> None:
        expected = {
            "tool-list": ("tool-logo-orbit", "icon-badge-wide", "overlay"),
            "credibility": ("credential-plaque", "avatar-bio-card",
                            "dark-full"),
            "evidence": ("evidence-map", "whiteboard-map", "cream-full"),
        }
        for shape, wanted in expected.items():
            form = forms_for_shape(FACE_BRIDGE_PROFILE, shape)[0]
            contract = form_contract(FACE_BRIDGE_PROFILE, form) or {}
            self.assertEqual((form, contract["kind"], contract["chassis"]),
                             wanted)

    def test_allocator_returns_form_kind_and_chassis(self) -> None:
        shapes = ["process", "comparison", "list", "scale"]
        beats = []
        for index, shape in enumerate(shapes):
            forms = forms_for_shape(FACE_BRIDGE_PROFILE, shape)
            beats.append({"beatId": f"b-{index}", "shape": shape,
                          "outStart": index * 10.0,
                          "compatibleForms": forms,
                          "preferredForm": forms[0]})
        result = build_form_allocation(
            beats, selected_profile=FACE_BRIDGE_PROFILE)
        rows = result["recommendedAssignment"]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row.get("informationForm") and row.get("kind")
                            and row.get("chassis") for row in rows), rows)
        self.assertEqual({row["chassis"] for row in rows}, {"cream", "dark"})
        self.assertGreaterEqual(result["maximumFeasibleDistinctForms"], 4)

    def test_allocator_maximizes_dense_window_before_later_novelty(self) -> None:
        shapes = ["process", "comparison", "credibility", "list", "evidence",
                  "thesis", "process"]
        times = [16.0, 20.0, 25.0, 62.0, 70.0, 86.0, 220.0]
        beats = []
        for index, (shape, out_start) in enumerate(zip(shapes, times)):
            forms = forms_for_shape(FACE_BRIDGE_PROFILE, shape)
            beats.append({"beatId": f"dense-{index}", "shape": shape,
                          "outStart": out_start, "compatibleForms": forms,
                          "preferredForm": forms[0]})
        result = build_form_allocation(
            beats, selected_profile=FACE_BRIDGE_PROFILE)
        self.assertEqual(result["denseWindowSelectedDistinctForms"],
                         result["denseWindowMaximumFeasibleDistinctForms"])

    def test_binding_requires_information_form_alternatives(self) -> None:
        forms = forms_for_shape(FACE_BRIDGE_PROFILE, "process")
        contract = form_contract(FACE_BRIDGE_PROFILE, forms[0]) or {}
        beat = {"beatId": "b-0", "shape": "process", "outStart": 15.0,
                "compatibleForms": forms, "compatibleKinds": list(dict.fromkeys(
                    (form_contract(FACE_BRIDGE_PROFILE, form) or {})["kind"]
                    for form in forms)), "visualProfile": FACE_BRIDGE_PROFILE,
                "minimumGraphicHoldS": 2.0, "decisionRequired": True}
        entry = _entry(0, forms[0], 13.5, 24.0)
        decision = {"beatId": "b-0", "decision": "graphic",
                    "graphicId": "g-0", "kind": contract["kind"],
                    "informationForm": forms[0],
                    "alternativeFormsConsidered": forms[1:3],
                    "selectionReason": "The status anatomy matches this handoff.",
                    "reason": "The transcript names a visible process."}
        plan = {"target": {"mode": "longform", "scope": "produced"},
                "graphicsTrack": [entry]}
        self.assertIsNone(decision_error(beat, decision, plan))
        decision.pop("alternativeFormsConsidered")
        self.assertIn("alternativeFormsConsidered",
                      decision_error(beat, decision, plan) or "")

    def test_retarget_preserves_each_chassis_renderer_contract(self) -> None:
        takeover = face_bridge._retarget_candidate(
            {"kind": "fragment-payoff", "spec": {}, "reason": "thesis"})
        self.assertEqual(takeover["kind"], "module-takeover")
        self.assertNotIn("presenterFrame", takeover["spec"])
        ledger = face_bridge._retarget_candidate(
            {"kind": "whiteboard-connector", "spec": {}, "reason": "flow"})
        self.assertTrue(ledger["spec"]["presenterFrame"])
        rail = face_bridge._retarget_candidate(
            {"kind": "module-bullet-bars", "spec": {}, "reason": "limit"})
        self.assertEqual(rail["anchor"], "beside-face")


class FaceBridgeReleaseTests(unittest.TestCase):
    def test_renderer_reuse_is_checked_across_the_complete_excerpt(self) -> None:
        cfg = {"forbidAdjacentRendererReuse": True,
               "maximumRendererUses": 2}
        rows = [{"kind": "module-rail"},
                {"kind": "module-rail"},
                {"kind": "module-takeover"},
                {"kind": "module-rail"}]
        errors = _renderer_errors(rows, cfg)
        self.assertTrue(any("consecutive" in error for error in errors), errors)
        self.assertTrue(any("maximum is 2" in error for error in errors), errors)

    def test_valid_two_chassis_sequence_passes(self) -> None:
        report = Report()
        check_style_profile(_plan(), 60.0, report)
        self.assertEqual(report.errors, [])

    def test_generic_renderer_substitution_fails(self) -> None:
        plan = _plan()
        plan["graphicsTrack"][1]["kind"] = "fragment-payoff"
        report = Report()
        check_style_profile(plan, 60.0, report)
        self.assertTrue(any("requires kind" in error for error in report.errors),
                        report.errors)

    def test_missing_evidence_payload_fails(self) -> None:
        plan = _plan()
        plan["graphicsTrack"][1]["spec"].pop("evidenceSource")
        report = Report()
        check_style_profile(plan, 60.0, report)
        self.assertTrue(any("missing required payload" in error
                            for error in report.errors), report.errors)

    def test_camera_punch_cannot_replace_module_motion(self) -> None:
        plan = _plan()
        plan["punchIns"] = [{"outStart": 20.0, "outEnd": 22.0,
                            "zoom": 1.25}]
        report = Report()
        check_style_profile(plan, 60.0, report)
        self.assertTrue(any("spend motion on modules" in error
                            for error in report.errors), report.errors)

    def test_measured_recompose_uses_the_structural_zoom_band(self) -> None:
        plan = _plan()
        plan["punchIns"] = [{"outStart": 20.0, "outEnd": 22.0,
                            "zoom": 1.33, "role": "recompose"}]
        report = Report()
        check_style_profile(plan, 60.0, report)
        self.assertFalse(any("spend motion on modules" in error
                             for error in report.errors), report.errors)

    def test_variety_counts_information_forms_not_shared_renderers(self) -> None:
        forms = ["step-sequence", "resolved-checklist", "thesis-statement",
                 "dated-timeline", "comparison-bars", "kv-rail",
                 "config-ledger", "status-queue"]
        graphics, decisions = [], []
        for index, information_form in enumerate(forms):
            contract = form_contract(FACE_BRIDGE_PROFILE, information_form) or {}
            graphic_id, beat_id = f"g-v-{index}", f"b-v-{index}"
            graphics.append({"id": graphic_id, "semanticBeatId": beat_id,
                             "informationForm": information_form,
                             "kind": contract["kind"], "outStart": index * 5.0,
                             "outEnd": index * 5.0 + 5.0})
            decisions.append({"beatId": beat_id, "decision": "graphic",
                              "graphicId": graphic_id,
                              "informationForm": information_form,
                              "kind": contract["kind"]})
        plan = {"target": {"mode": "longform", "scope": "produced"},
                "graphicsTrack": graphics, "graphicsDecisions": decisions}
        report = Report()
        check_variety(plan, "longform", report, 40.0)
        self.assertEqual(report.errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

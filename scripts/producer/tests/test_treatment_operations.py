"""P4 typed treatment handlers preserve unrelated authority and close locally."""
from __future__ import annotations

import copy
import unittest

from edit.exact_timing import PositiveRational
from planner.treatment_contract import TreatmentContractError
from planner.treatment_models import TreatmentState
from planner.treatment_operations import apply_treatment_operation
from tests.scene_fixtures import fire_sparkles_scene

BUNDLE_HASH = "b" * 64


def _state() -> TreatmentState:
    plan = {
        "cutTrack": [{"sourceId": "source-main", "srcStart": 0, "srcEnd": 60}],
        "transitions": [{
            "id": "seam-hook", "outFrame": 300, "outTime": 10.0,
            "kind": "white-flash", "sfx": False,
        }],
        "baselineLook": {
            "zoom": 1.2, "centerX": 0.5, "centerY": 0.45, "grade": "none",
        },
        "music": {"enabled": False},
    }
    return TreatmentState(
        plan, (fire_sparkles_scene(BUNDLE_HASH),),
        PositiveRational(30, 1), 1800)


def _base(operation: str) -> dict:
    return {"schemaVersion": 1, "operation": operation}


class TreatmentOperationTests(unittest.TestCase):
    def test_title_text_invalidates_only_its_render_unit(self) -> None:
        operation = {
            **_base("title.setText"),
            "sceneId": "scene-045", "elementId": "right-copy",
            "variable": "rightTitle", "text": "Repaired copy",
            "expectedText": "Change only this card",
            "expectedSceneVersion": 1,
        }
        result = apply_treatment_operation(_state(), operation)
        scene = result.state.scenes[0]
        self.assertEqual(
            scene["composition"]["variables"]["rightTitle"], "Repaired copy")
        self.assertEqual(scene["version"], 2)
        self.assertEqual(result.state.plan, _state().plan)
        self.assertIn(
            "scene-unit-media:scene-045:unit-right",
            result.receipt["invalidatedNodes"])
        self.assertNotIn(
            "scene-unit-media:scene-045:unit-left",
            result.receipt["invalidatedNodes"])
        self.assertFalse(result.receipt["mediaReused"])

    def test_exposed_scene_variable_has_the_same_unit_closure(self) -> None:
        operation = {
            **_base("scene.setVariable"),
            "sceneId": "scene-045", "elementId": "left-blue-card",
            "variable": "leftColor", "value": "#0011AA",
            "expectedValue": "#0B5FFF", "expectedSceneVersion": 1,
        }
        result = apply_treatment_operation(_state(), operation)
        self.assertIn(
            "scene-unit-media:scene-045:unit-left",
            result.receipt["invalidatedNodes"])
        self.assertEqual(
            result.state.scenes[0]["elements"][0]["values"]["leftColor"],
            "#0011AA")

    def test_same_duration_scene_move_reuses_media(self) -> None:
        operation = {
            **_base("scene.move"), "sceneId": "scene-045",
            "startFrame": 1500, "endFrameExclusive": 1680,
            "timelineMapHash": "d" * 64, "expectedSceneVersion": 1,
        }
        result = apply_treatment_operation(_state(), operation)
        self.assertTrue(result.receipt["mediaReused"])
        self.assertNotIn(
            "scene-media:scene-045", result.receipt["invalidatedNodes"])
        self.assertEqual(result.receipt["dirtyWindows"], [
            {"startFrame": 1350, "endFrameExclusive": 1530},
            {"startFrame": 1500, "endFrameExclusive": 1680},
        ])

    def test_duration_change_rerenders_scene_media(self) -> None:
        operation = {
            **_base("scene.move"), "sceneId": "scene-045",
            "startFrame": 1350, "endFrameExclusive": 1590,
            "timelineMapHash": "e" * 64, "expectedSceneVersion": 1,
        }
        result = apply_treatment_operation(_state(), operation)
        self.assertFalse(result.receipt["mediaReused"])
        self.assertIn(
            "scene-media:scene-045", result.receipt["invalidatedNodes"])

    def test_scene_add_and_remove_have_exact_composite_closures(self) -> None:
        added = fire_sparkles_scene(BUNDLE_HASH)
        added["sceneId"] = "scene-010"
        added["timing"].update({
            "startFrame": 300, "endFrameExclusive": 480,
            "timelineMapHash": "f" * 64,
        })
        add = apply_treatment_operation(
            _state(), {**_base("scene.add"), "scene": added})
        self.assertEqual(len(add.state.scenes), 2)
        self.assertIn("scene-media:scene-010",
                      add.receipt["invalidatedNodes"])
        remove = apply_treatment_operation(_state(), {
            **_base("scene.remove"), "sceneId": "scene-045",
            "expectedSceneVersion": 1,
        })
        self.assertEqual(remove.state.scenes, ())
        self.assertTrue(remove.receipt["mediaReused"])
        self.assertNotIn("scene-media:scene-045",
                         remove.receipt["invalidatedNodes"])

    def test_transition_move_dirties_old_and_new_seams(self) -> None:
        before = {
            "id": "seam-hook", "outFrame": 300,
            "kind": "white-flash", "sfx": False,
        }
        after = {**before, "outFrame": 600, "kind": "light-leak"}
        result = apply_treatment_operation(_state(), {
            **_base("transition.set"), "transitionId": "seam-hook",
            "expectedValue": before, "value": after,
        })
        self.assertEqual(
            [row["startFrame"] for row in result.receipt["dirtyWindows"]],
            [285, 585])
        self.assertEqual(result.state.plan["transitions"][0]["outTime"], 20.0)
        self.assertEqual(result.receipt["invalidatedNodes"],
                         ["base-video", "transition-video"])

    def test_sfx_change_keeps_picture_nodes_reusable(self) -> None:
        result = apply_treatment_operation(_state(), {
            **_base("sfx.set"), "transitionId": "seam-hook",
            "expectedSfx": False, "sfx": True,
        })
        self.assertTrue(result.receipt["mediaReused"])
        self.assertEqual(result.receipt["invalidatedNodes"], [
            "final-mux", "master-audio", "transition-audio"])
        self.assertTrue(result.state.plan["transitions"][0]["sfx"])
        self.assertEqual(
            result.state.plan["baselineLook"], _state().plan["baselineLook"])

    def test_grade_change_truthfully_dirties_the_full_picture(self) -> None:
        result = apply_treatment_operation(_state(), {
            **_base("grade.set"), "expectedGrade": "none", "grade": "warm",
        })
        self.assertEqual(result.receipt["dirtyWindows"], [
            {"startFrame": 0, "endFrameExclusive": 1800}])
        self.assertEqual(result.receipt["invalidatedNodes"], [
            "base-video-full", "final-video", "graphics-composite-full"])
        self.assertFalse(result.receipt["mediaReused"])
        self.assertEqual(result.state.plan["baselineLook"]["zoom"], 1.2)

    def test_unknown_fields_stale_versions_and_preconditions_fail_closed(self) -> None:
        operation = {
            **_base("title.setText"),
            "sceneId": "scene-045", "elementId": "right-copy",
            "variable": "rightTitle", "text": "New",
            "expectedText": "wrong", "expectedSceneVersion": 1,
        }
        with self.assertRaisesRegex(TreatmentContractError, "precondition"):
            apply_treatment_operation(_state(), operation)
        stale = {**operation, "expectedText": "Change only this card",
                 "expectedSceneVersion": 2}
        with self.assertRaisesRegex(TreatmentContractError, "version"):
            apply_treatment_operation(_state(), stale)
        extra = {**operation, "surprise": True}
        with self.assertRaisesRegex(TreatmentContractError, "extras"):
            apply_treatment_operation(_state(), extra)
        unknown = copy.deepcopy(operation)
        unknown["operation"] = "execute.arbitrary"
        with self.assertRaisesRegex(TreatmentContractError, "unsupported"):
            apply_treatment_operation(_state(), unknown)

    def test_element_edit_cannot_silently_change_a_shared_scene_variable(self) -> None:
        """A single-element request cannot change both fire and sparkles via global seed."""
        state = _state()
        before = copy.deepcopy(state)
        operation = {**_base("scene.setVariable"), "sceneId": "scene-045",
                     "elementId": "seeded-fire", "variable": "seed",
                     "expectedValue": 424242, "value": 424243, "expectedSceneVersion": 1}
        with self.assertRaisesRegex(TreatmentContractError, "shared"):
            apply_treatment_operation(state, operation)
        self.assertEqual(state, before)

    def test_element_precondition_also_requires_matching_composition_value(self) -> None:
        """A stale element label cannot overwrite a different actual composition value."""
        state = _state()
        state.scenes[0]["composition"]["variables"]["rightTitle"] = "Different existing copy"
        before = copy.deepcopy(state)
        operation = {**_base("title.setText"), "sceneId": "scene-045",
                     "elementId": "right-copy", "variable": "rightTitle",
                     "expectedText": "Change only this card", "text": "Repaired copy",
                     "expectedSceneVersion": 1}
        with self.assertRaisesRegex(TreatmentContractError, "composition"):
            apply_treatment_operation(state, operation)
        self.assertEqual(state, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)

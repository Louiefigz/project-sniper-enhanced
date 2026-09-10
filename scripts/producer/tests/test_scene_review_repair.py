"""Private one-unit scene review repair contract regressions."""
from __future__ import annotations

import copy
import hashlib
import unittest
from unittest import mock

from edit.exact_timing import PositiveRational
from graphics.scene_contract import SceneContractError, canonical_json
from graphics.scene_package_contract import ResolvedScenePackage
from graphics.scene_review_repair import (
    SceneReviewRepairRequest,
    repair_scene_review,
)
from planner.treatment_models import TreatmentState
from planner.treatment_operations import apply_treatment_operation
from tests.scene_fixtures import fire_sparkles_scene


def _seal(value: dict) -> dict:
    return {**value, "receiptHash": hashlib.sha256(
        canonical_json(value)).hexdigest()}


def _bindings(scene: dict, right_hash: str) -> dict:
    entries = []
    for unit in scene["renderUnits"]:
        media_hash = "1" * 64 if unit["unitId"] == "unit-left" else right_hash
        entries.append({
            "bindingId": f"{scene['sceneId']}-{unit['unitId']}",
            "unitId": unit["unitId"], "elementIds": unit["elementIds"],
            "zIndex": unit["zIndex"],
            "compositeMode": unit["compositeMode"],
            "timing": scene["timing"],
            "media": {"path": f"/media/{media_hash}.mov",
                      "sha256": media_hash},
        })
    return {
        "kind": "palmier-scene-bindings",
        "sceneId": scene["sceneId"], "entries": entries,
    }


def _render_receipt(
    package_hash: str, scene: dict, right_hash: str,
    cached: dict[str, bool],
) -> dict:
    body = {
        "schemaVersion": 1, "kind": "scene-package-render",
        "packageHash": package_hash, "sceneId": scene["sceneId"],
        "sceneVersion": scene["version"], "admission": {},
        "renderReceipts": [
            {"unitId": "unit-left", "cached": cached["unit-left"]},
            {"unitId": "unit-right", "cached": cached["unit-right"]},
        ],
        "palmierBindings": _bindings(scene, right_hash),
        "checks": [],
    }
    return _seal(body)


def _revision() -> tuple[dict, dict, dict]:
    previous = fire_sparkles_scene("a" * 64)
    state = TreatmentState(
        {}, (previous,), PositiveRational(30, 1), 1800)
    result = apply_treatment_operation(state, {
        "schemaVersion": 1, "operation": "title.setText",
        "sceneId": "scene-045", "elementId": "right-copy",
        "variable": "rightTitle", "text": "Repaired right card copy",
        "expectedText": "Change only this card", "expectedSceneVersion": 1,
    })
    return previous, result.state.scenes[0], result.receipt


def _resolved(scene: dict, package_hash: str) -> ResolvedScenePackage:
    return ResolvedScenePackage(
        {}, scene, package_hash, {}, None, None)


def _projects(previous: dict, current: dict) -> tuple[dict, dict]:
    rows = [{
        "sceneId": f"scene-{index:03d}",
        "packageHash": hashlib.sha256(
            f"scene-{index:03d}".encode()).hexdigest(),
        "sceneVersion": 1,
        "startFrame": index * 20,
        "endFrameExclusive": index * 20 + 10,
    } for index in range(50) if index != 45]
    timing = previous["timing"]
    rows.append({
        "sceneId": previous["sceneId"], "packageHash": "b" * 64,
        "sceneVersion": previous["version"],
        "startFrame": timing["startFrame"],
        "endFrameExclusive": timing["endFrameExclusive"],
    })
    base = {
        "sha256": "4" * 64, "durationFrames": 1800,
        "fps": {"numerator": 30, "denominator": 1},
        "width": 1920, "height": 1080, "sampleRate": 48_000,
    }
    before = {
        "schemaVersion": 1, "projectId": "project-review-test",
        "base": base, "scenes": rows,
    }
    after = copy.deepcopy(before)
    after["scenes"][-1].update({
        "packageHash": "c" * 64, "sceneVersion": current["version"],
    })
    return before, after


def _request(
    left_cached: bool = True, right_cached: bool = False,
) -> tuple[SceneReviewRepairRequest, dict]:
    previous, current, operation = _revision()
    old_hash, new_hash = "b" * 64, "c" * 64
    before = _render_receipt(
        old_hash, previous, "2" * 64,
        {"unit-left": True, "unit-right": True})
    after = _render_receipt(
        new_hash, current, "3" * 64,
        {"unit-left": left_cached, "unit-right": right_cached})
    before_project, after_project = _projects(previous, current)
    request = SceneReviewRepairRequest(
        previous=_resolved(previous, old_hash),
        current=_resolved(current, new_hash),
        previous_project=before_project,
        current_project=after_project,
        operation_receipt=operation,
        previous_render_receipt=before,
        base_channel_receipt={},
        cache_dir="/cache", base_path="/base.mov",
        output_path="/review.mov",
    )
    return request, after


def _patches(after: dict):
    return (
        mock.patch(
            "graphics.scene_review_repair.read_scene_bindings",
            side_effect=lambda value, _scene: value),
        mock.patch(
            "graphics.scene_review_repair._render_current",
            return_value=after),
        mock.patch(
            "graphics.scene_review_repair.media_identity",
            return_value={"path": "/base.mov", "sha256": "4" * 64}),
        mock.patch(
            "graphics.scene_review_repair.render_review_fragment",
            return_value={"output": {"sha256": "5" * 64}}),
    )


class SceneReviewRepairTests(unittest.TestCase):
    def _run(self, request: SceneReviewRepairRequest, after: dict) -> dict:
        contexts = _patches(after)
        with contexts[0], contexts[1], contexts[2], contexts[3]:
            return repair_scene_review(request)

    def test_first_review_renders_only_changed_unit_and_never_base(self) -> None:
        request, after = _request()
        result = self._run(request, after)
        self.assertEqual(result["unitWork"], {
            "logicalDirtyUnitIds": ["unit-right"],
            "renderedUnitIds": ["unit-right"],
            "reusedUnitIds": ["unit-left"],
        })
        self.assertEqual(result["execution"]["unitRenderCount"], 1)
        self.assertEqual(result["execution"]["fullBaseEncodeCount"], 0)
        self.assertEqual(result["execution"]["fullDurationOutputCount"], 0)
        self.assertEqual(result["projectFanout"]["sceneCount"], 50)
        self.assertEqual(result["projectFanout"]["dirtySceneIds"], ["scene-045"])
        self.assertEqual(result["projectFanout"]["reusedSceneCount"], 49)
        self.assertEqual(result["promotion"]["activeMutationCount"], 0)
        self.assertTrue({
            "graphics/scene_review_repair.py",
            "graphics/scene_review_media.py",
            "graphics/scene_review_repair_cli.py",
            "audio/channel_normalization.py",
            "edit/exact_timing.py",
            "palmier/scene_bindings.py",
        }.issubset(result["implementation"]["files"]))
        self.assertEqual(
            len(result["implementation"]["producerRenderToolchainHash"]), 64)

    def test_exact_replay_may_hit_changed_unit_cache(self) -> None:
        request, after = _request(right_cached=True)
        result = self._run(request, after)
        self.assertEqual(result["unitWork"]["renderedUnitIds"], [])
        self.assertEqual(
            result["unitWork"]["reusedUnitIds"],
            ["unit-left", "unit-right"])
        self.assertEqual(result["execution"]["unitRenderCount"], 0)

    def test_unrelated_unit_cache_miss_fails_closed(self) -> None:
        request, after = _request(left_cached=False)
        with self.assertRaisesRegex(
                SceneContractError, "unrelated unit"):
            self._run(request, after)

    def test_operation_receipt_tamper_fails_before_render(self) -> None:
        request, after = _request()
        request.operation_receipt["dirtyWindows"][0]["startFrame"] += 1
        with self.assertRaisesRegex(SceneContractError, "receipt hash"):
            self._run(request, after)

    def test_unrelated_project_scene_change_fails_before_render(self) -> None:
        request, after = _request()
        request.current_project["scenes"][0]["packageHash"] = "d" * 64
        with self.assertRaisesRegex(
                SceneContractError, "exactly the repaired scene"):
            self._run(request, after)

    def test_project_base_drift_fails_before_render(self) -> None:
        request, after = _request()
        request.current_project["base"]["sha256"] = "d" * 64
        with self.assertRaisesRegex(
                SceneContractError, "approved base authority"):
            self._run(request, after)

    def test_project_timing_drift_fails_before_render(self) -> None:
        request, after = _request()
        target = request.current_project["scenes"][-1]
        target["startFrame"] += 1
        with self.assertRaisesRegex(
                SceneContractError, "structure or timing"):
            self._run(request, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)

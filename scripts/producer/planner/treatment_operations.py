"""Deterministic P4 scene/title/transition/SFX/grade treatment handlers."""
from __future__ import annotations

import copy
import hashlib
import json

from edit.exact_timing import PositiveRational
from graphics.scene_contract import validate_scene
from graphics.visual_source_receipt import carry_scene_source_choice
from planner.treatment_contract import (
    TreatmentContractError,
    validate_treatment_operation,
)
from planner.treatment_models import (
    TreatmentEffect,
    TreatmentResult,
    TreatmentState,
)
from planner.treatment_plan_handlers import grade_set, sfx_set, transition_set


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TreatmentContractError(
            "treatment state is not canonical JSON") from exc


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_state(value: TreatmentState) -> TreatmentState:
    if not isinstance(value.plan, dict):
        raise TreatmentContractError("treatment plan must be an object")
    if type(value.total_frames) is not int or value.total_frames < 1:
        raise TreatmentContractError("total_frames must be positive")
    if not isinstance(value.fps, PositiveRational):
        raise TreatmentContractError("fps must be an exact PositiveRational")
    scenes = tuple(validate_scene(scene) for scene in value.scenes)
    ids = [scene["sceneId"] for scene in scenes]
    if len(ids) != len(set(ids)):
        raise TreatmentContractError("treatment scenes contain duplicate IDs")
    _canonical({"plan": value.plan, "scenes": scenes})
    return TreatmentState(value.plan, scenes, value.fps, value.total_frames)


def _clone(state: TreatmentState) -> tuple[dict, list[dict]]:
    return copy.deepcopy(state.plan), copy.deepcopy(list(state.scenes))


def _scene_index(scenes: list[dict], scene_id: str) -> int:
    matches = [index for index, scene in enumerate(scenes)
               if scene["sceneId"] == scene_id]
    if len(matches) != 1:
        raise TreatmentContractError(
            f"scene {scene_id!r} did not resolve exactly once")
    return matches[0]


def _expected_scene(scene: dict, operation: dict) -> None:
    if scene["version"] != operation["expectedSceneVersion"]:
        raise TreatmentContractError("scene version precondition failed")


def _exact_equal(first: object, second: object) -> bool:
    return type(first) is type(second) and first == second


def _window(scene: dict) -> tuple[int, int]:
    timing = scene["timing"]
    return timing["startFrame"], timing["endFrameExclusive"]


def _single_variable(scene: dict, element: dict, variable: str) -> None:
    """Require one owner and one current value before a scoped element mutation."""
    owners = [row for row in scene["elements"] if variable in row["values"]]
    if len(owners) != 1:
        raise TreatmentContractError(
            "shared scene variable cannot be changed by a single-element operation")
    if not _exact_equal(scene["composition"]["variables"][variable], element["values"][variable]):
        raise TreatmentContractError("scene composition variable precondition failed")


def _scene_add(state: TreatmentState, operation: dict) -> TreatmentEffect:
    plan, scenes = _clone(state)
    scene = copy.deepcopy(operation["scene"])
    if any(item["sceneId"] == scene["sceneId"] for item in scenes):
        raise TreatmentContractError("scene.add target already exists")
    if scene["timing"]["fps"] != state.fps.to_dict() \
            or scene["timing"]["endFrameExclusive"] > state.total_frames:
        raise TreatmentContractError("scene.add timing is outside project authority")
    scenes.append(scene)
    target = scene["sceneId"]
    next_state = TreatmentState(plan, tuple(scenes), state.fps, state.total_frames)
    return TreatmentEffect(next_state, (_window(scene),), (
        f"scene-media:{target}", f"composite:{target}",
        f"palmier-binding:{target}"), False, target)


def _scene_value(state: TreatmentState, operation: dict) -> TreatmentEffect:
    """Apply a current, uniquely owned property without changing another element."""
    plan, scenes = _clone(state)
    index = _scene_index(scenes, operation["sceneId"])
    scene = scenes[index]
    _expected_scene(scene, operation)
    element = next((row for row in scene["elements"]
                    if row["elementId"] == operation["elementId"]), None)
    variable = operation["variable"]
    if element is None or variable not in element["exposedProperties"] \
            or variable not in element["values"] \
            or variable not in scene["composition"]["variables"]:
        raise TreatmentContractError("scene variable is not exposed by target")
    _single_variable(scene, element, variable)
    before = element["values"][variable]
    expected_key = ("expectedText" if operation["operation"] == "title.setText"
                    else "expectedValue")
    value_key = "text" if operation["operation"] == "title.setText" else "value"
    if not _exact_equal(before, operation[expected_key]):
        raise TreatmentContractError("scene variable precondition failed")
    element["values"][variable] = operation[value_key]
    scene["composition"]["variables"][variable] = operation[value_key]
    scene["version"] += 1
    carry_scene_source_choice(state.scenes[index], scene, 'variable')
    validate_scene(scene)
    unit = next((row["unitId"] for row in scene["renderUnits"]
                 if element["elementId"] in row["elementIds"]), None)
    if unit is None:
        raise TreatmentContractError("scene element has no render unit")
    target = scene["sceneId"]
    next_state = TreatmentState(plan, tuple(scenes), state.fps, state.total_frames)
    return TreatmentEffect(next_state, (_window(scene),), (
        f"scene-unit-media:{target}:{unit}", f"composite:{target}",
        f"palmier-binding:{target}:{unit}"), False, target)


def _scene_move(state: TreatmentState, operation: dict) -> TreatmentEffect:
    plan, scenes = _clone(state)
    index = _scene_index(scenes, operation["sceneId"])
    scene = scenes[index]
    _expected_scene(scene, operation)
    old = _window(scene)
    new = operation["startFrame"], operation["endFrameExclusive"]
    if new[1] > state.total_frames:
        raise TreatmentContractError("scene.move exceeds project duration")
    same_duration = old[1] - old[0] == new[1] - new[0]
    scene["timing"].update({
        "startFrame": new[0], "endFrameExclusive": new[1],
        "timelineMapHash": operation["timelineMapHash"]})
    scene["version"] += 1
    carry_scene_source_choice(state.scenes[index], scene, 'timing')
    validate_scene(scene)
    target = scene["sceneId"]
    nodes = [f"composite:{target}", f"palmier-binding:{target}"]
    if not same_duration:
        nodes.append(f"scene-media:{target}")
    next_state = TreatmentState(plan, tuple(scenes), state.fps, state.total_frames)
    return TreatmentEffect(
        next_state, (old, new), tuple(nodes), same_duration, target)


def _scene_remove(state: TreatmentState, operation: dict) -> TreatmentEffect:
    plan, scenes = _clone(state)
    index = _scene_index(scenes, operation["sceneId"])
    scene = scenes[index]
    _expected_scene(scene, operation)
    scenes.pop(index)
    target = scene["sceneId"]
    next_state = TreatmentState(plan, tuple(scenes), state.fps, state.total_frames)
    return TreatmentEffect(next_state, (_window(scene),), (
        f"composite:{target}", f"palmier-binding:{target}"), True, target)


_HANDLERS = {
    "scene.add": _scene_add,
    "scene.setVariable": _scene_value,
    "scene.move": _scene_move,
    "scene.remove": _scene_remove,
    "title.setText": _scene_value,
    "transition.set": transition_set,
    "sfx.set": sfx_set,
    "grade.set": grade_set,
}


def _unrelated(state: TreatmentState, action: str, target: str) -> dict:
    plan, scenes = _clone(state)
    if action.startswith("scene.") or action == "title.setText":
        scenes = [scene for scene in scenes if scene["sceneId"] != target]
        return {"plan": plan, "scenes": scenes}
    if action in {"transition.set", "sfx.set"}:
        plan["transitions"] = [
            row for row in plan.get("transitions") or []
            if not isinstance(row, dict) or row.get("id") != target]
        return {"plan": plan, "scenes": scenes}
    if action == "grade.set":
        look = dict(plan.get("baselineLook") or {})
        look.pop("grade", None)
        plan["baselineLook"] = look
    return {"plan": plan, "scenes": scenes}


def apply_treatment_operation(state: TreatmentState,
                              raw_operation: object) -> TreatmentResult:
    """Apply one closed operation and prove its unrelated authority stayed fixed."""
    current = _validate_state(state)
    operation = validate_treatment_operation(raw_operation)
    effect = _HANDLERS[operation["operation"]](current, operation)
    candidate = _validate_state(effect.state)
    before_unrelated = _hash(_unrelated(
        current, operation["operation"], effect.target_id))
    after_unrelated = _hash(_unrelated(
        candidate, operation["operation"], effect.target_id))
    if before_unrelated != after_unrelated:
        raise TreatmentContractError("treatment changed unrelated authority")
    receipt = {
        "schemaVersion": 1, "operation": operation["operation"],
        "operationHash": _hash(operation),
        "beforeStateHash": _hash({
            "plan": current.plan, "scenes": current.scenes}),
        "afterStateHash": _hash({
            "plan": candidate.plan, "scenes": candidate.scenes}),
        "targetId": effect.target_id,
        "dirtyWindows": [
            {"startFrame": start, "endFrameExclusive": end}
            for start, end in sorted(set(effect.dirty))],
        "invalidatedNodes": sorted(set(effect.nodes)),
        "mediaReused": effect.media_reused,
        "unrelatedAuthorityHash": before_unrelated,
    }
    return TreatmentResult(candidate, {
        **receipt, "receiptHash": _hash(receipt)})

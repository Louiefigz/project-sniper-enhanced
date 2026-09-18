"""Private one-unit scene review repair with no full-program base encode."""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass

from graphics.scene_contract import SceneContractError, canonical_json
from graphics.scene_package_contract import ResolvedScenePackage
from graphics.scene_package_render import (
    ScenePackageRenderRequest,
    render_scene_package,
)
from graphics.scene_review_implementation import implementation_closure
from graphics.scene_review_media import (
    SceneReviewMediaRequest,
    media_identity,
    render_review_fragment,
)
from graphics.scene_review_project import (
    SceneProjectRevisionRequest,
    validate_project_revision,
)
from palmier.scene_binding_reader import read_scene_bindings
from palmier.scene_bindings import scene_binding_delta

_RENDER_KEYS = {
    "schemaVersion", "kind", "packageHash", "sceneId", "sceneVersion",
    "admission", "renderReceipts", "palmierBindings", "checks", "receiptHash",
}
_OPERATION_KEYS = {
    "schemaVersion", "operation", "operationHash", "beforeStateHash",
    "afterStateHash", "targetId", "dirtyWindows", "invalidatedNodes",
    "mediaReused", "unrelatedAuthorityHash", "receiptHash",
}


@dataclass(frozen=True)
class SceneReviewRepairRequest:
    """All immutable authority and output locations for one private review."""

    previous: ResolvedScenePackage
    current: ResolvedScenePackage
    previous_project: dict
    current_project: dict
    operation_receipt: dict
    previous_render_receipt: dict
    base_channel_receipt: dict
    cache_dir: str
    base_path: str
    output_path: str
    workers: int = 2
    sample_rate: int = 48_000


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _assert_hashed_receipt(
    value: object, keys: set[str], label: str,
) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise SceneContractError(f"{label} has an invalid field set")
    receipt = value.get("receiptHash")
    body = {key: item for key, item in value.items()
            if key != "receiptHash"}
    if receipt != _hash(body):
        raise SceneContractError(f"{label} receipt hash changed")
    return value


def _revision_surface(scene: dict) -> dict:
    value = copy.deepcopy(scene)
    value["version"] = 1
    value["composition"]["variables"] = {
        key: None for key in value["composition"]["variables"]}
    for element in value["elements"]:
        element["values"] = {key: None for key in element["values"]}
    return value


def _element_changes(
        current: dict, previous: dict, variables: dict) -> set[str]:
    changed = {key for key in current["values"]
               if current["values"][key] != previous["values"][key]}
    if any(current["values"][key] != variables[key] for key in changed):
        raise SceneContractError(
            "scene element values disagree with composition variables")
    return changed


def _changed_values(previous: dict, current: dict) -> tuple[set[str], set[str]]:
    before_vars = previous["composition"]["variables"]
    after_vars = current["composition"]["variables"]
    if set(before_vars) != set(after_vars):
        raise SceneContractError(
            "scene review repair cannot add or remove variables")
    variables = {
        key for key in before_vars if before_vars[key] != after_vars[key]}
    elements: set[str] = set()
    observed: set[str] = set()
    before_elements = {row["elementId"]: row for row in previous["elements"]}
    for row in current["elements"]:
        old = before_elements[row["elementId"]]
        changed = _element_changes(row, old, after_vars)
        if changed:
            elements.add(row["elementId"])
            observed.update(changed)
    if not variables or observed != variables:
        raise SceneContractError(
            "scene review variable and element changes are inconsistent")
    return variables, elements


def _changed_unit(previous: dict, current: dict) -> str:
    if current["version"] != previous["version"] + 1 \
            or _revision_surface(previous) != _revision_surface(current):
        raise SceneContractError(
            "scene review repair changed structure, timing, or authority")
    _variables, elements = _changed_values(previous, current)
    units = {
        row["unitId"] for row in current["renderUnits"]
        if elements.intersection(row["elementIds"])
    }
    if len(units) != 1:
        raise SceneContractError(
            "scene review repair must affect exactly one render unit")
    return units.pop()


def _previous_receipt(
    request: SceneReviewRepairRequest,
) -> dict:
    value = _assert_hashed_receipt(
        request.previous_render_receipt, _RENDER_KEYS,
        "previous scene render")
    expected = {
        "schemaVersion": 1, "kind": "scene-package-render",
        "packageHash": request.previous.package_hash,
        "sceneId": request.previous.scene["sceneId"],
        "sceneVersion": request.previous.scene["version"],
    }
    if any(value.get(key) != item for key, item in expected.items()):
        raise SceneContractError(
            "previous render receipt binds another scene package")
    read_scene_bindings(
        value["palmierBindings"], request.previous.scene)
    return value


def _operation(
    request: SceneReviewRepairRequest, unit_id: str,
) -> dict:
    value = _assert_hashed_receipt(
        request.operation_receipt, _OPERATION_KEYS,
        "scene treatment operation")
    scene = request.current.scene
    timing = scene["timing"]
    expected_nodes = sorted({
        f"scene-unit-media:{scene['sceneId']}:{unit_id}",
        f"composite:{scene['sceneId']}",
        f"palmier-binding:{scene['sceneId']}:{unit_id}",
    })
    valid = (
        value["schemaVersion"] == 1
        and value["operation"] in {"title.setText", "scene.setVariable"}
        and value["targetId"] == scene["sceneId"]
        and value["dirtyWindows"] == [{
            "startFrame": timing["startFrame"],
            "endFrameExclusive": timing["endFrameExclusive"],
        }]
        and value["invalidatedNodes"] == expected_nodes
        and value["mediaReused"] is False
    )
    if not valid:
        raise SceneContractError(
            "scene operation receipt does not authorize one-unit review")
    return value


def _render_current(
    request: SceneReviewRepairRequest,
) -> dict:
    value = render_scene_package(ScenePackageRenderRequest(
        request.current, request.cache_dir, workers=request.workers))
    _assert_hashed_receipt(value, _RENDER_KEYS, "current scene render")
    expected = {
        "packageHash": request.current.package_hash,
        "sceneId": request.current.scene["sceneId"],
        "sceneVersion": request.current.scene["version"],
    }
    if any(value.get(key) != item for key, item in expected.items()):
        raise SceneContractError(
            "current render receipt binds another scene package")
    return value


def _render_evidence(
    previous: dict, current: dict, unit_id: str,
) -> tuple[dict, dict]:
    delta = scene_binding_delta(
        previous["palmierBindings"], current["palmierBindings"])
    operations = delta["operations"]
    binding_id = f"{current['sceneId']}-{unit_id}"
    if len(operations) != 1 \
            or operations[0]["action"] != "replace-media" \
            or operations[0]["bindingId"] != binding_id:
        raise SceneContractError(
            "scene review render did not replace exactly one unit")
    rows = {row["unitId"]: row for row in current["renderReceipts"]}
    expected = {
        row["unitId"] for row in current["palmierBindings"]["entries"]}
    if set(rows) != expected \
            or any(not row["cached"] for key, row in rows.items()
                   if key != unit_id):
        raise SceneContractError(
            "scene review render rebuilt an unrelated unit")
    cache = {
        "logicalDirtyUnitIds": [unit_id],
        "renderedUnitIds": sorted(
            key for key, row in rows.items() if not row["cached"]),
        "reusedUnitIds": sorted(
            key for key, row in rows.items() if row["cached"]),
    }
    return delta, cache


def _project_fanout(
    request: SceneReviewRepairRequest, base_identity: dict,
) -> dict:
    return validate_project_revision(SceneProjectRevisionRequest(
        previous=request.previous_project,
        current=request.current_project,
        previous_package_hash=request.previous.package_hash,
        current_package_hash=request.current.package_hash,
        previous_scene=request.previous.scene,
        target_scene=request.current.scene,
        base_identity=base_identity,
        sample_rate=request.sample_rate,
    ))


def repair_scene_review(request: SceneReviewRepairRequest) -> dict:
    """Build one private scene window; never build or promote a full master."""
    previous = _previous_receipt(request)
    unit_id = _changed_unit(
        request.previous.scene, request.current.scene)
    operation = _operation(request, unit_id)
    base_before = media_identity(request.base_path)
    project = _project_fanout(request, base_before)
    current = _render_current(request)
    delta, cache = _render_evidence(previous, current, unit_id)
    review = render_review_fragment(SceneReviewMediaRequest(
        request.current.scene, current["palmierBindings"],
        request.base_path, request.output_path,
        request.base_channel_receipt, request.sample_rate))
    base_after = media_identity(request.base_path)
    if base_before != base_after:
        raise SceneContractError(
            "approved base changed during private scene review")
    timing = request.current.scene["timing"]
    value = {
        "schemaVersion": 1, "kind": "scene-unit-review-repair",
        "sceneId": request.current.scene["sceneId"],
        "previousPackageHash": request.previous.package_hash,
        "currentPackageHash": request.current.package_hash,
        "operationReceiptHash": operation["receiptHash"],
        "previousRenderReceiptHash": previous["receiptHash"],
        "currentRenderReceiptHash": current["receiptHash"],
        "dirtyFrameWindow": {
            "startFrame": timing["startFrame"],
            "endFrameExclusive": timing["endFrameExclusive"],
        },
        "unitWork": cache, "bindingDelta": delta,
        "projectFanout": project,
        "baseBefore": base_before, "baseAfter": base_after,
        "reviewMedia": review,
        "implementation": implementation_closure(),
        "execution": {
            "fullBaseEncodeCount": 0,
            "fullDurationOutputCount": 0,
            "reviewFragmentEncodeCount": 1,
            "unitRenderCount": len(cache["renderedUnitIds"]),
            "unitReuseCount": len(cache["reusedUnitIds"]),
            "outputScope": "dirty-scene-window-only",
        },
        "promotion": {
            "status": "private-review", "activeMutationCount": 0,
            "connectedPalmierMutationCount": 0,
        },
    }
    return {**value, "receiptHash": _hash(value)}

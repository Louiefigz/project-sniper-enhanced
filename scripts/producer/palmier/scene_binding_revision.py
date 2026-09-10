"""Compile one proved scene-media delta into Desktop Palmier revision work."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from graphics.scene_contract import canonical_json
from palmier.mcp_client import PalmierError
from palmier.revision_schema import validate_revision
from palmier.scene_binding_reader import read_scene_bindings
from palmier.scene_binding_revision_contract import (
    digest,
    validate_binding_pair,
)
from palmier.scene_bindings import SceneBindingError, scene_binding_delta
from palmier.scene_media import SceneMediaError, stable_scene_media_hash

_MARKER_KEYS = {
    "schemaVersion", "kind", "sceneId", "previousBindingSetHash",
    "currentBindingSetHash", "deltaHash", "preservedBindingIds",
}
_OPERATION_KEYS = {
    "lane", "action", "elementId", "expectedVersion", "before", "after",
    "sourceAnchor", "sceneBindingReplacement", "operationId",
}


@dataclass(frozen=True)
class SceneBindingRevisionInput:
    """Authorities required to mint one candidate-bound scene revision."""

    previous_scene: dict
    current_scene: dict
    previous_bindings: dict
    current_bindings: dict
    delta: dict
    element_ledger: dict
    candidate_fingerprint: str
    base_plan_hash: str
    next_plan_hash: str


def _binding(entries: dict, ident: str, label: str) -> dict:
    matches = [row for row in entries.get("entries") or []
               if isinstance(row, dict) and row.get("bindingId") == ident]
    if len(matches) != 1:
        raise PalmierError(f"{label} scene binding is not unique")
    return matches[0]


def _current_ledger(ledger: object, ident: str) -> dict:
    if not isinstance(ledger, dict) or ledger.get("schemaVersion") not in {1, 2}:
        raise PalmierError("scene replacement requires an element ledger")
    elements = ledger.get("elements")
    row = elements.get(ident) if isinstance(elements, dict) else None
    if not isinstance(row, dict) or row.get("status") != "current":
        raise PalmierError("scene binding has no current Palmier ledger element")
    return row


def _ledger_match(row: dict, before: dict, expected_version: object) -> None:
    timing = before["timing"]
    expected = {
        "lane": "graphics", "assetHash": before["media"]["sha256"],
        "assetPath": before["media"]["path"],
        "startFrame": timing["startFrame"],
        "endFrame": timing["endFrameExclusive"],
    }
    if any(row.get(key) != value for key, value in expected.items()):
        raise PalmierError("scene binding disagrees with the current element ledger")
    identities = (row.get("clipId"), row.get("mediaRef"))
    track = row.get("trackIndex")
    if not all(isinstance(value, str) and value for value in identities) \
            or isinstance(track, bool) or not isinstance(track, int) or track < 0:
        raise PalmierError("scene binding ledger lacks clip/media/track identity")
    if row.get("version", 1) != expected_version:
        raise PalmierError("scene binding ledger version is stale")


def _marker(request: SceneBindingRevisionInput, delta: dict) -> dict:
    return {
        "schemaVersion": 1, "kind": "palmier-scene-binding-replacement",
        "sceneId": request.current_bindings["sceneId"],
        "previousBindingSetHash": request.previous_bindings["bindingSetHash"],
        "currentBindingSetHash": request.current_bindings["bindingSetHash"],
        "deltaHash": delta["deltaHash"],
        "preservedBindingIds": delta["preservedBindingIds"],
    }


def _operation(request: SceneBindingRevisionInput, delta: dict) -> dict:
    operations = delta["operations"]
    if len(operations) != 1 or operations[0].get("action") != "replace-media":
        raise PalmierError("scene revision requires exactly one media replacement")
    ident = operations[0].get("bindingId")
    if not isinstance(ident, str) or ident in delta["preservedBindingIds"]:
        raise PalmierError("scene replacement binding identity is invalid")
    before = _binding(request.previous_bindings, ident, "previous")
    after = _binding(request.current_bindings, ident, "current")
    validate_binding_pair(before, after, ident)
    row = _current_ledger(request.element_ledger, ident)
    version = row.get("version", 1)
    _ledger_match(row, before, version)
    return {
        "lane": "graphics", "action": "replace",
        "elementId": ident, "expectedVersion": version,
        "before": before, "after": after,
        "sourceAnchor": request.current_bindings["sceneId"],
        "sceneBindingReplacement": _marker(request, delta),
    }


def _validated_bindings(request: SceneBindingRevisionInput) -> tuple[dict, dict]:
    try:
        previous = read_scene_bindings(
            request.previous_bindings, request.previous_scene)
        current = read_scene_bindings(
            request.current_bindings, request.current_scene)
    except SceneBindingError as exc:
        raise PalmierError(f"scene binding revision is invalid: {exc}") from exc
    if current["sceneVersion"] != previous["sceneVersion"] + 1:
        raise PalmierError("scene replacement must advance exactly one version")
    return previous, current


def build_scene_binding_revision(request: SceneBindingRevisionInput) -> dict:
    """Mint a standard one-operation revision for the Desktop executor."""
    previous, current = _validated_bindings(request)
    expected = scene_binding_delta(previous, current)
    if request.delta != expected:
        raise PalmierError("scene binding delta is stale or not exact")
    for value, label in (
        (request.candidate_fingerprint, "candidate fingerprint"),
        (request.base_plan_hash, "base plan hash"),
        (request.next_plan_hash, "next plan hash"),
    ):
        digest(value, label)
    normalized = SceneBindingRevisionInput(
        request.previous_scene, request.current_scene, previous, current,
        expected, request.element_ledger, request.candidate_fingerprint,
        request.base_plan_hash, request.next_plan_hash)
    operation = _operation(normalized, expected)
    timing = operation["after"]["timing"]
    rate = Fraction(
        int(timing["fps"]["numerator"]), int(timing["fps"]["denominator"]))
    dirty = [float(Fraction(timing["startFrame"], 1) / rate),
             float(Fraction(timing["endFrameExclusive"], 1) / rate)]
    return validate_revision({
        "basePlanHash": request.base_plan_hash,
        "nextPlanHash": request.next_plan_hash,
        "baseCandidateFingerprint": request.candidate_fingerprint,
        "operations": [operation],
        "dependencies": {
            "changedLanes": ["sceneBindings"], "dirtyWindows": [dirty],
            "requiresFullRebuild": False,
        },
    })


def is_scene_binding_operation(operation: object) -> bool:
    """Whether one standard revision operation carries scene authority."""
    return isinstance(operation, dict) \
        and "sceneBindingReplacement" in operation


def _runtime_operation(operation: dict) -> tuple[dict, dict, dict]:
    if set(operation) != _OPERATION_KEYS or operation.get("lane") != "graphics" \
            or operation.get("action") != "replace":
        raise PalmierError("scene revision operation has unsupported fields")
    marker = operation.get("sceneBindingReplacement")
    if not isinstance(marker, dict) or set(marker) != _MARKER_KEYS \
            or marker.get("schemaVersion") != 1 \
            or marker.get("kind") != "palmier-scene-binding-replacement":
        raise PalmierError("scene replacement marker is malformed")
    for key in ("previousBindingSetHash", "currentBindingSetHash", "deltaHash"):
        digest(marker.get(key), f"scene replacement {key}")
    before, after = validate_binding_pair(
        operation.get("before"), operation.get("after"),
        operation["elementId"])
    return marker, before, after


def _delta_current(marker: dict, before: dict, after: dict) -> None:
    preserved = marker.get("preservedBindingIds")
    if not isinstance(preserved, list) or preserved != sorted(set(preserved)) \
            or before["bindingId"] in preserved:
        raise PalmierError("scene replacement preserved-binding set is invalid")
    body = {
        "schemaVersion": 1, "kind": "palmier-scene-binding-delta",
        "sceneId": marker["sceneId"],
        "operations": [{
            "action": "replace-media", "bindingId": before["bindingId"],
            "before": before["media"], "after": after["media"],
        }],
        "preservedBindingIds": preserved,
    }
    if hashlib.sha256(canonical_json(body)).hexdigest() != marker["deltaHash"]:
        raise PalmierError("scene replacement delta hash is stale")


def _runtime_media(after: dict) -> tuple[str, str]:
    try:
        path, digest = stable_scene_media_hash(after["media"].get("path"))
    except SceneMediaError as exc:
        raise PalmierError(f"scene replacement media is unsafe: {exc}") from exc
    if digest != after["media"].get("sha256"):
        raise PalmierError("scene replacement media bytes changed")
    return path, digest


def _runtime_rate(timing: dict, context: Any) -> None:
    value = timing.get("fps")
    if not isinstance(value, dict):
        raise PalmierError("scene replacement has no rational frame rate")
    try:
        rate = float(Fraction(int(value["numerator"]), int(value["denominator"])))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise PalmierError("scene replacement frame rate is malformed") from exc
    if rate != context.fps:
        raise PalmierError("scene replacement rate differs from Palmier project")
    end = timing.get("endFrameExclusive")
    if not isinstance(end, int) or end > context.total_frames:
        raise PalmierError("scene replacement window leaves the Palmier timeline")


def prepare_scene_binding_steps(operation: dict, context: Any) -> list[dict]:
    """Map one scene binding to exact import/replace Desktop worklist steps."""
    marker, before, after = _runtime_operation(operation)
    if marker["sceneId"] != operation["sourceAnchor"]:
        raise PalmierError("scene replacement anchor disagrees with its scene")
    _delta_current(marker, before, after)
    row = _current_ledger(context.ledger, operation["elementId"])
    _ledger_match(row, before, operation["expectedVersion"])
    _runtime_rate(after["timing"], context)
    path, digest = _runtime_media(after)
    operation_id = operation["operationId"]
    common = {
        "elementId": operation["elementId"],
        "revisionOperationId": operation_id,
        "sceneBindingId": operation["elementId"],
        "sceneBindingDeltaHash": marker["deltaHash"],
    }
    imported = {
        "op": "import", "key": f"scene-revision:{operation['elementId']}",
        "path": path, "fileHash": digest,
        "importName": operation["elementId"],
        "mutationId": f"{operation_id}:import", **common,
    }
    timing = after["timing"]
    replacement = {
        "op": "replace-overlay", "lane": "graphics",
        "startFrame": timing["startFrame"],
        "endFrame": timing["endFrameExclusive"],
        "path": path, "fileHash": digest,
        "assetPath": path, "assetHash": digest,
        "oldClipId": row["clipId"], "oldMediaRef": row["mediaRef"],
        "trackIndex": row["trackIndex"], "transform": row.get("transform"),
        "sourceAnchor": marker["sceneId"],
        "mutationId": f"{operation_id}:replace", **common,
    }
    return [imported, replacement]

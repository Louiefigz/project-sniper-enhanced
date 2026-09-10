"""Fail-closed readback validator for baked-regenerable scene bindings."""
from __future__ import annotations

import hashlib

from graphics.scene_contract import canonical_json, scene_hash, validate_scene
from palmier.scene_bindings import SceneBindingError
from palmier.scene_media import SceneMediaError, stable_scene_media_hash

_DIGESTS = frozenset("0123456789abcdef")
_ROOT_KEYS = {
    "schemaVersion", "kind", "sceneId", "sceneVersion", "captionPolicy",
    "sourceSceneHash", "entries", "bindingSetHash",
}
_ENTRY_KEYS = {
    "bindingId", "unitId", "elementIds", "zIndex", "compositeMode",
    "timing", "media", "regeneration", "bindingHash",
}


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in _DIGESTS for char in value):
        raise SceneBindingError(f"{label} must be a lowercase SHA-256")
    return value


def _object(value: object, label: str, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise SceneBindingError(f"{label} has an invalid field set")
    return value


def _media(value: object, catalog: bool) -> dict:
    common = {"path", "sha256", "renderKey"}
    motion = ({"catalogSourceHash", "motionContractHash"} if catalog
              else {"animationMapHash"})
    row = _object(value, "scene binding media", common | motion)
    try:
        _, actual_hash = stable_scene_media_hash(row["path"])
    except SceneMediaError as exc:
        raise SceneBindingError(str(exc)) from exc
    for key in row:
        if key != "path":
            _digest(row[key], f"scene binding media {key}")
    if actual_hash != row["sha256"]:
        raise SceneBindingError("scene binding media bytes changed after projection")
    return row


def _timing(scene: dict) -> dict:
    value = scene["timing"]
    return {
        "startFrame": value["startFrame"],
        "endFrameExclusive": value["endFrameExclusive"],
        "fps": value["fps"],
        "timelineMapHash": value["timelineMapHash"],
    }


def _expected(scene: dict) -> dict[str, dict]:
    modes = {row["palmierGranularity"] for row in scene["renderUnits"]}
    if modes == {"scene"}:
        return {f"{scene['sceneId']}-full-scene": {
            "unitId": None,
            "elementIds": [row["elementId"] for row in scene["elements"]],
            "zIndex": min(row["zIndex"] for row in scene["renderUnits"]),
            "compositeMode": "normal",
            "regenerationKind": "scene-render-full",
        }}
    if modes != {"unit"}:
        raise SceneBindingError("mixed Palmier scene granularity is unsupported")
    return {f"{scene['sceneId']}-{unit['unitId']}": {
        "unitId": unit["unitId"], "elementIds": unit["elementIds"],
        "zIndex": unit["zIndex"], "compositeMode": unit["compositeMode"],
        "regenerationKind": "scene-render-unit",
    } for unit in scene["renderUnits"]}


def _entry(row: object, expected: dict, scene: dict, source_hash: str) -> dict:
    value = _object(row, "scene binding entry", _ENTRY_KEYS)
    if value["bindingId"] not in expected:
        raise SceneBindingError("scene binding id is outside the scene contract")
    contract = expected[value["bindingId"]]
    for key in ("unitId", "elementIds", "zIndex", "compositeMode"):
        if value[key] != contract[key]:
            raise SceneBindingError("scene binding placement disagrees with scene")
    if value["timing"] != _timing(scene):
        raise SceneBindingError("scene binding timing disagrees with scene")
    regeneration = _object(
        value["regeneration"], "scene binding regeneration",
        {"kind", "sceneHash", "sceneVersion", "unitId"})
    expected_regeneration = {
        "kind": contract["regenerationKind"], "sceneHash": source_hash,
        "sceneVersion": scene["version"], "unitId": contract["unitId"],
    }
    if regeneration != expected_regeneration:
        raise SceneBindingError("scene regeneration authority disagrees")
    _media(value["media"], scene["composition"]["type"] == "catalog")
    binding_hash = _digest(value["bindingHash"], "scene binding hash")
    body = {key: item for key, item in value.items() if key != "bindingHash"}
    if hashlib.sha256(canonical_json(body)).hexdigest() != binding_hash:
        raise SceneBindingError("scene binding hash does not match its fields")
    return value


def read_scene_bindings(value: object, scene_value: object) -> dict:
    """Reobserve exact scene placement, media, and regeneration authority."""
    scene = validate_scene(scene_value)
    row = _object(value, "Palmier scene bindings", _ROOT_KEYS)
    source_hash = scene_hash(scene)
    expected_root = {
        "schemaVersion": 1, "kind": "palmier-scene-bindings",
        "sceneId": scene["sceneId"], "sceneVersion": scene["version"],
        "captionPolicy": scene["captionPolicy"], "sourceSceneHash": source_hash,
    }
    if any(row[key] != item for key, item in expected_root.items()):
        raise SceneBindingError("Palmier scene-binding authority disagrees")
    entries = row["entries"]
    expected = _expected(scene)
    if not isinstance(entries, list) or len(entries) != len(expected):
        raise SceneBindingError("Palmier scene-binding closure is incomplete")
    parsed = [_entry(item, expected, scene, source_hash) for item in entries]
    if {item["bindingId"] for item in parsed} != set(expected):
        raise SceneBindingError("Palmier scene binding IDs are incomplete")
    binding_hash = _digest(row["bindingSetHash"], "binding set hash")
    body = {key: item for key, item in row.items() if key != "bindingSetHash"}
    if hashlib.sha256(canonical_json(body)).hexdigest() != binding_hash:
        raise SceneBindingError("Palmier binding-set hash does not match")
    return row

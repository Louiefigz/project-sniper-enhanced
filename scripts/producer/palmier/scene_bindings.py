"""Verified baked-but-regenerable scene-unit bindings for Palmier."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from graphics.scene_contract import canonical_json, scene_hash, validate_scene
from palmier.scene_media import SceneMediaError, stable_scene_media_hash

_SHA256 = frozenset("0123456789abcdef")


class SceneBindingError(RuntimeError):
    """A rendered scene cannot cross the Palmier handoff boundary."""


@dataclass(frozen=True)
class SceneBindingInput:
    """Validated scene authority plus its exact render receipts."""

    scene: dict
    receipts: tuple[dict, ...]


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in _SHA256 for char in value):
        raise SceneBindingError(f"{label} must be a lowercase SHA-256")
    return value


def _media_identity(value: object) -> tuple[str, str]:
    try:
        return stable_scene_media_hash(value)
    except SceneMediaError as exc:
        raise SceneBindingError(str(exc)) from exc


def _motion_identity(receipt: dict, scene: dict) -> dict:
    if scene["composition"]["type"] == "catalog":
        return {
            "catalogSourceHash": _digest(
                receipt.get("catalogSourceHash"), "catalog source hash"),
            "motionContractHash": _digest(
                receipt.get("motionContractHash"), "motion contract hash"),
        }
    return {"animationMapHash": _digest(
        receipt.get("animationMapHash"), "animation map hash")}


def _receipt(receipt: object, scene: dict,
             expected_unit: str | None) -> dict:
    if not isinstance(receipt, dict):
        raise SceneBindingError("scene render receipt must be an object")
    expected = {
        "schemaVersion": 1, "sceneId": scene["sceneId"],
        "sceneVersion": scene["version"], "unitId": expected_unit,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise SceneBindingError("scene render receipt authority does not match")
    path, actual_hash = _media_identity(receipt.get("path"))
    render_key = _digest(receipt.get("renderKey"), "render key")
    motion = _motion_identity(receipt, scene)
    proof = receipt.get("proof")
    asset = proof.get("asset") if isinstance(proof, dict) else None
    media_hash = _digest(
        asset.get("sha256") if isinstance(asset, dict) else None,
        "proved scene media")
    if actual_hash != media_hash:
        raise SceneBindingError("scene media bytes do not match render proof")
    return {
        "path": path, "sha256": media_hash, "renderKey": render_key,
        **motion,
    }


def _timing(scene: dict) -> dict:
    value = scene["timing"]
    return {
        "startFrame": value["startFrame"],
        "endFrameExclusive": value["endFrameExclusive"],
        "fps": value["fps"],
        "timelineMapHash": value["timelineMapHash"],
    }


def _unit_binding(scene: dict, unit: dict, media: dict,
                  source_hash: str) -> dict:
    value = {
        "bindingId": f"{scene['sceneId']}-{unit['unitId']}",
        "unitId": unit["unitId"],
        "elementIds": unit["elementIds"],
        "zIndex": unit["zIndex"],
        "compositeMode": unit["compositeMode"],
        "timing": _timing(scene),
        "media": media,
        "regeneration": {
            "kind": "scene-render-unit",
            "sceneHash": source_hash,
            "sceneVersion": scene["version"],
            "unitId": unit["unitId"],
        },
    }
    return {**value, "bindingHash": hashlib.sha256(canonical_json(value)).hexdigest()}


def _scene_binding(scene: dict, media: dict, source_hash: str) -> dict:
    value = {
        "bindingId": f"{scene['sceneId']}-full-scene",
        "unitId": None,
        "elementIds": [row["elementId"] for row in scene["elements"]],
        "zIndex": min(row["zIndex"] for row in scene["renderUnits"]),
        "compositeMode": "normal",
        "timing": _timing(scene),
        "media": media,
        "regeneration": {
            "kind": "scene-render-full",
            "sceneHash": source_hash,
            "sceneVersion": scene["version"],
            "unitId": None,
        },
    }
    return {**value, "bindingHash": hashlib.sha256(canonical_json(value)).hexdigest()}


def _receipt_index(receipts: tuple[dict, ...]) -> dict[object, dict]:
    indexed: dict[object, dict] = {}
    for receipt in receipts:
        key = receipt.get("unitId") if isinstance(receipt, dict) else object()
        if key in indexed:
            raise SceneBindingError("duplicate scene render receipt")
        indexed[key] = receipt
    return indexed


def build_scene_bindings(request: SceneBindingInput) -> dict:
    """Bind proved media to exact Palmier placement and regeneration inputs."""
    scene = validate_scene(request.scene)
    modes = {row["palmierGranularity"] for row in scene["renderUnits"]}
    if len(modes) != 1:
        raise SceneBindingError("mixed Palmier scene granularity is unsupported")
    indexed = _receipt_index(request.receipts)
    source_hash = scene_hash(scene)
    if modes == {"scene"}:
        if set(indexed) != {None}:
            raise SceneBindingError("full-scene Palmier binding needs one receipt")
        entries = [_scene_binding(
            scene, _receipt(indexed[None], scene, None), source_hash)]
    else:
        expected = {row["unitId"] for row in scene["renderUnits"]}
        if set(indexed) != expected:
            raise SceneBindingError("scene-unit render receipt closure is incomplete")
        entries = [
            _unit_binding(
                scene, unit, _receipt(indexed[unit["unitId"]], scene,
                                      unit["unitId"]), source_hash)
            for unit in sorted(scene["renderUnits"], key=lambda row: row["zIndex"])
        ]
    value = {
        "schemaVersion": 1, "kind": "palmier-scene-bindings",
        "sceneId": scene["sceneId"], "sceneVersion": scene["version"],
        "captionPolicy": scene["captionPolicy"],
        "sourceSceneHash": source_hash, "entries": entries,
    }
    return {**value, "bindingSetHash": hashlib.sha256(
        canonical_json(value)).hexdigest()}


def _by_id(value: dict, label: str) -> dict[str, dict]:
    rows = value.get("entries")
    if value.get("kind") != "palmier-scene-bindings" \
            or not isinstance(rows, list):
        raise SceneBindingError(f"{label} scene bindings are malformed")
    indexed = {row.get("bindingId"): row for row in rows
               if isinstance(row, dict)}
    if len(indexed) != len(rows) or None in indexed:
        raise SceneBindingError(f"{label} scene binding identities are invalid")
    return indexed


def _placement_surface(binding: dict) -> dict:
    return {key: binding.get(key) for key in (
        "bindingId", "unitId", "elementIds", "zIndex", "compositeMode",
    )}


def _binding_change(ident: str, old: dict | None,
                    new: dict | None) -> dict | None:
    if old is None or new is None:
        return {
            "action": "add" if old is None else "remove",
            "bindingId": ident, "before": old, "after": new,
        }
    if old["media"] != new["media"]:
        return {
            "action": "replace-media", "bindingId": ident,
            "before": old["media"], "after": new["media"],
        }
    if old["timing"] != new["timing"]:
        return {
            "action": "move-placement", "bindingId": ident,
            "before": old["timing"], "after": new["timing"],
        }
    if _placement_surface(old) == _placement_surface(new):
        return None
    return {
        "action": "replace-binding", "bindingId": ident,
        "before": old, "after": new,
    }


def scene_binding_delta(previous: dict, current: dict) -> dict:
    """Return exact unit replacements/moves while preserving other bindings."""
    if previous.get("sceneId") != current.get("sceneId"):
        raise SceneBindingError("scene binding revisions target different scenes")
    before, after = _by_id(previous, "previous"), _by_id(current, "current")
    operations, preserved = [], []
    for ident in sorted(set(before) | set(after)):
        old, new = before.get(ident), after.get(ident)
        change = _binding_change(ident, old, new)
        if change is None:
            preserved.append(ident)
        else:
            operations.append(change)
    value = {
        "schemaVersion": 1, "kind": "palmier-scene-binding-delta",
        "sceneId": current["sceneId"], "operations": operations,
        "preservedBindingIds": preserved,
    }
    return {**value, "deltaHash": hashlib.sha256(canonical_json(value)).hexdigest()}

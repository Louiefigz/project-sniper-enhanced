"""SceneSpecV1 adapter for measured legacy catalog compositions."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

from graphics.comp_capability_artifact import (
    MOTION_DIR,
    composition_source_closure,
)
from graphics.comp_capabilities import capability_matrix
from graphics.delivery_geometry import own_screen_meta
from graphics.graphics_render import (
    comp_path,
    render_entry_at_rate as render_entry,
)
from graphics.pip_hole import entry_has_hole
from graphics.render_rate import normalize_render_rate
from graphics.scene_contract import (
    SceneContractError,
    canonical_json,
    validate_scene,
)
from graphics.template_contract import (
    composition_dimensions,
    resolved_assets,
    validate_entry,
)


@dataclass(frozen=True)
class CatalogSceneRequest:
    """Closed inputs used to wrap one registered composition."""

    entry: dict
    scene_id: str
    timing: dict
    canvas: dict
    provenance: dict
    version: int = 1
    caption_policy: str = "preserve"


def _capability(kind: str) -> tuple[dict, str]:
    row = capability_matrix().get(kind)
    if not isinstance(row, dict):
        raise SceneContractError(
            f"catalog kind {kind!r} lacks fresh measured capability")
    path = comp_path(kind)
    with open(path, encoding="utf-8") as handle:
        html = handle.read()
    measured = tuple(row["canvas"])
    if composition_dimensions(html) != measured:
        raise SceneContractError(
            f"catalog kind {kind!r} declaration disagrees with measurement")
    return row, html


def _target_canvas(value: object, measured: tuple[int, int]) -> dict:
    if not isinstance(value, dict) or set(value) != {"width", "height"}:
        raise SceneContractError("catalog target canvas must name width/height")
    if any(type(item) is not int or item <= 0 for item in value.values()):
        raise SceneContractError("catalog target canvas must use positive integers")
    target = value["width"], value["height"]
    if abs(target[0] / target[1] - measured[0] / measured[1]) > 0.002:
        raise SceneContractError(
            "catalog composition and delivery canvas aspects do not match")
    return {"width": target[0], "height": target[1]}


def _asset_id(field: str, index: int) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", field.lower()).strip("-")
    if not normalized or not normalized[0].isalpha():
        normalized = f"asset-{index}"
    return f"{normalized}-{index}"


def _resolved_asset_rows(entry: dict, html: str) -> list[dict]:
    rows = []
    for index, asset in enumerate(resolved_assets(entry, html), start=1):
        path = asset["path"]
        if os.path.realpath(path) != path or os.path.islink(path):
            raise SceneContractError(
                "catalog selector source must be one canonical file")
        with open(path, "rb") as handle:
            data = handle.read()
        rows.append({
            "kind": "asset",
            "id": _asset_id(str(asset["field"]), index),
            "sha256": hashlib.sha256(data).hexdigest(),
            "sizeBytes": len(data), "field": asset["field"],
            "selector": asset["selector"], "sourcePath": path,
        })
    return rows


def _dependencies(entry: dict, html: str) -> list[dict]:
    return [{key: row[key] for key in ("kind", "id", "sha256")}
            for row in _resolved_asset_rows(entry, html)]


def _render_mode(entry: dict) -> str:
    if entry_has_hole(entry):
        return "presenter-hole"
    return ("takeover-opaque" if entry.get("anchor") == "own-screen"
            else "overlay-alpha")


def _validate_duration(entry: dict, timing: dict) -> None:
    rate = normalize_render_rate(timing["fps"])
    expected = (
        timing["endFrameExclusive"] - timing["startFrame"]) / rate.numeric
    try:
        actual = float(entry["outEnd"]) - float(entry["outStart"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SceneContractError(
            "catalog entry requires finite outStart/outEnd") from exc
    if abs(actual - expected) > 0.5 / rate.numeric + 1e-9:
        raise SceneContractError(
            "catalog entry duration disagrees with exact scene timing")


def wrap_catalog_scene(request: CatalogSceneRequest) -> dict:
    """Build a validated SceneSpecV1 from one measured catalog entry."""
    entry = request.entry
    if not isinstance(entry, dict) or not isinstance(entry.get("kind"), str):
        raise SceneContractError("catalog entry must name a kind")
    kind = entry["kind"]
    capability, html = _capability(kind)
    _validate_duration(entry, request.timing)
    validate_entry(entry, html)
    measured = tuple(capability["canvas"])
    canvas = _target_canvas(request.canvas, measured)
    variables = dict(entry.get("spec") or {})
    scene = {
        "schemaVersion": 1, "sceneId": request.scene_id,
        "version": request.version, "timing": request.timing,
        "canvas": canvas, "renderMode": _render_mode(entry),
        "composition": {
            "type": "catalog", "kind": kind, "variables": variables},
        "elements": [{
            "elementId": "catalog-content", "role": "catalog-content",
            "exposedProperties": sorted(variables), "values": variables,
        }],
        "renderUnits": [{
            "unitId": "catalog-scene", "elementIds": ["catalog-content"],
            "zIndex": 0, "entry": f"compositions/{kind}.html",
            "compositeMode": "normal", "palmierGranularity": "scene",
        }],
        "captionPolicy": request.caption_policy,
        "dependencies": _dependencies(entry, html),
        "provenance": request.provenance,
    }
    return validate_scene(scene)


def _entry_from_scene(scene: dict) -> tuple[dict, object]:
    timing = scene["timing"]
    rate = normalize_render_rate(timing["fps"])
    frames = timing["endFrameExclusive"] - timing["startFrame"]
    composition = scene["composition"]
    anchor = ("own-screen" if scene["renderMode"] in {
        "takeover-opaque", "presenter-hole"}
              else "free-band")
    return {
        "kind": composition["kind"], "anchor": anchor,
        "outStart": 0.0, "outEnd": frames / rate.numeric,
        "spec": composition["variables"],
    }, rate.token


def _source_rows(kind: str, html: str) -> list[dict]:
    sources = composition_source_closure(html)
    sources[os.path.relpath(comp_path(kind), MOTION_DIR)] = html.encode("utf-8")
    return [{
        "path": relative,
        "sha256": hashlib.sha256(data).hexdigest(),
        "sizeBytes": len(data),
    } for relative, data in sorted(sources.items())]


def catalog_scene_contract(scene: dict) -> dict:
    """Bind a catalog scene to fresh capability and exact source closure."""
    valid = validate_scene(scene)
    composition = valid["composition"]
    if composition["type"] != "catalog":
        raise SceneContractError("catalog contract requires catalog composition")
    kind = composition["kind"]
    capability, html = _capability(kind)
    entry, _ = _entry_from_scene(valid)
    validate_entry(entry, html)
    files = _source_rows(kind, html)
    capability_hash = hashlib.sha256(canonical_json(capability)).hexdigest()
    source_hash = hashlib.sha256(canonical_json(files)).hexdigest()
    asset_bindings = _resolved_asset_rows(entry, html)
    dependencies = [{key: row[key] for key in ("kind", "id", "sha256")}
                    for row in asset_bindings]
    order = lambda row: (row["kind"], row["id"])
    if sorted(valid["dependencies"], key=order) != sorted(
            dependencies, key=order):
        raise SceneContractError(
            "catalog scene dependencies differ from resolved selectors")
    motion = {
        "scene": valid, "capabilityHash": capability_hash,
        "catalogSourceHash": source_hash, "assetBindings": asset_bindings,
    }
    return {
        "schemaVersion": 1, "catalogKind": kind,
        "catalogSourceHash": source_hash,
        "motionContractHash": hashlib.sha256(
            canonical_json(motion)).hexdigest(),
        "capabilityHash": capability_hash, "sourceFiles": files,
        "assetBindings": asset_bindings,
    }


def render_catalog_scene(scene: dict, cache_dir: str | None = None) -> dict:
    """Render a catalog SceneSpec through the existing proved catalog lane."""
    valid = validate_scene(scene)
    composition = valid["composition"]
    if composition["type"] != "catalog":
        raise SceneContractError("catalog renderer requires catalog composition")
    capability, html = _capability(composition["kind"])
    target = valid["canvas"]["width"], valid["canvas"]["height"]
    _target_canvas(valid["canvas"], tuple(capability["canvas"]))
    entry, rate = _entry_from_scene(valid)
    validate_entry(entry, html)
    rendered = render_entry(entry, cache_dir, rate)
    geometry = None
    if valid["renderMode"] in {"takeover-opaque", "presenter-hole"}:
        geometry = own_screen_meta(tuple(capability["canvas"]), target)[2]
    contract = catalog_scene_contract(valid)
    return {
        "schemaVersion": 1, "sceneId": valid["sceneId"],
        "sceneVersion": valid["version"], "unitId": None,
        "path": rendered["path"], "cached": rendered["cached"],
        "renderKey": rendered["key"], "proof": rendered["proof"],
        "catalogKind": composition["kind"], "fps": rate,
        "deliveryGeometry": geometry,
        "catalogSourceHash": contract["catalogSourceHash"],
        "motionContractHash": contract["motionContractHash"],
    }

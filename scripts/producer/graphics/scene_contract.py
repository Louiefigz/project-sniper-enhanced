"""Closed runtime contract for catalog and project-scoped motion scenes."""
from __future__ import annotations

import hashlib
import json
import math
import re
from fractions import Fraction
from typing import Any

SCHEMA_VERSION = 1
_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VARIABLE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_HTML = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*\.html$")
_SCALAR_TYPES = (str, int, float, bool)
_ROOT_KEYS = {
    "schemaVersion", "sceneId", "version", "timing", "canvas", "renderMode",
    "composition", "elements", "renderUnits", "captionPolicy",
    "dependencies", "provenance",
}

class SceneContractError(ValueError):
    """A scene cannot enter the authoring or rendering boundary."""

def canonical_json(value: object) -> bytes:
    """Canonical scene bytes used for hashes and immutable receipts."""
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SceneContractError(f"scene is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")

def scene_hash(scene: dict) -> str:
    """Full content identity of a validated scene."""
    validate_scene(scene)
    return hashlib.sha256(canonical_json(scene)).hexdigest()

def _object(value: object, label: str, keys: set[str]) -> dict:
    if not isinstance(value, dict):
        raise SceneContractError(f"{label} must be an object")
    extras = sorted(set(value) - keys)
    if extras:
        raise SceneContractError(f"{label} has unsupported fields: {extras}")
    return value

def _required(value: dict, label: str, keys: set[str]) -> None:
    missing = sorted(keys - set(value))
    if missing:
        raise SceneContractError(f"{label} is missing fields: {missing}")

def _stable_id(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) > 96 or not _ID.fullmatch(value):
        raise SceneContractError(f"{label} must be a stable kebab-case id")
    return value

def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise SceneContractError(f"{label} must be a lowercase SHA-256")
    return value

def _relative_html(value: object, label: str) -> str:
    parts = value.split("/") if isinstance(value, str) else []
    if not isinstance(value, str) or len(value) > 240 \
            or not _HTML.fullmatch(value) or value.startswith("/") \
            or any(part in {"", ".", ".."} for part in parts):
        raise SceneContractError(f"{label} must be a safe relative HTML path")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SceneContractError(f"{label} must be a positive integer")
    return value


def _rational(value: object, label: str) -> Fraction:
    row = _object(value, label, {"numerator", "denominator"})
    _required(row, label, {"numerator", "denominator"})
    values = []
    for key in ("numerator", "denominator"):
        raw = row[key]
        if not isinstance(raw, str) or not re.fullmatch(r"[1-9][0-9]*", raw):
            raise SceneContractError(f"{label}.{key} must be a canonical integer")
        values.append(int(raw))
    result = Fraction(values[0], values[1])
    if result.numerator != values[0] or result.denominator != values[1]:
        raise SceneContractError(f"{label} must be reduced")
    return result


def _timing(value: object) -> None:
    keys = {"startFrame", "endFrameExclusive", "fps", "timelineMapHash"}
    row = _object(value, "scene.timing", keys)
    _required(row, "scene.timing", keys)
    start = row["startFrame"]
    end = row["endFrameExclusive"]
    if isinstance(start, bool) or not isinstance(start, int) or start < 0:
        raise SceneContractError("scene.timing.startFrame must be nonnegative")
    if isinstance(end, bool) or not isinstance(end, int) or end <= start:
        raise SceneContractError("scene timing must be a non-empty half-open range")
    _rational(row["fps"], "scene.timing.fps")
    _digest(row["timelineMapHash"], "scene.timing.timelineMapHash")


def _canvas(value: object) -> None:
    row = _object(value, "scene.canvas", {"width", "height"})
    _required(row, "scene.canvas", {"width", "height"})
    for key in ("width", "height"):
        size = _positive_int(row[key], f"scene.canvas.{key}")
        if size > 8192 or size % 2:
            raise SceneContractError(f"scene.canvas.{key} must be even and <= 8192")


def _variables(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise SceneContractError(f"{label} must be an object")
    for key, item in value.items():
        if not isinstance(key, str) or not _VARIABLE.fullmatch(key):
            raise SceneContractError(f"{label} has invalid variable name {key!r}")
        if not isinstance(item, _SCALAR_TYPES) or isinstance(item, float) \
                and not math.isfinite(item):
            raise SceneContractError(f"{label}.{key} must be a finite scalar")
        if isinstance(item, str) and len(item) > 4000:
            raise SceneContractError(f"{label}.{key} exceeds 4000 characters")
    return value


def _composition(value: object) -> None:
    common = {"type", "variables"}
    if not isinstance(value, dict):
        raise SceneContractError("scene.composition must be an object")
    if value.get("type") == "catalog":
        keys = common | {"kind"}
        row = _object(value, "scene.composition", keys)
        _required(row, "scene.composition", keys)
        _stable_id(row["kind"], "scene.composition.kind")
    elif value.get("type") == "project":
        keys = common | {"bundleId", "bundleHash", "entry"}
        row = _object(value, "scene.composition", keys)
        _required(row, "scene.composition", keys)
        _stable_id(row["bundleId"], "scene.composition.bundleId")
        _digest(row["bundleHash"], "scene.composition.bundleHash")
        _relative_html(row["entry"], "scene.composition.entry")
    else:
        raise SceneContractError("scene.composition.type is unsupported")
    _variables(row["variables"], "scene.composition.variables")


def _elements(value: object) -> set[str]:
    if not isinstance(value, list) or not value:
        raise SceneContractError("scene.elements must be a non-empty array")
    ids: set[str] = set()
    for index, item in enumerate(value):
        label = f"scene.elements[{index}]"
        keys = {"elementId", "role", "exposedProperties", "values"}
        row = _object(item, label, keys)
        _required(row, label, keys)
        ident = _stable_id(row["elementId"], f"{label}.elementId")
        if ident in ids:
            raise SceneContractError(f"duplicate scene element {ident}")
        ids.add(ident)
        _stable_id(row["role"], f"{label}.role")
        props = row["exposedProperties"]
        if not isinstance(props, list) or len(set(props)) != len(props) \
                or not all(isinstance(key, str) and _VARIABLE.fullmatch(key)
                           for key in props):
            raise SceneContractError(f"{label}.exposedProperties is invalid")
        values = _variables(row["values"], f"{label}.values")
        if set(values) != set(props):
            raise SceneContractError(f"{label}.values must match exposedProperties")
    return ids


def _unit_row(item: object, index: int) -> tuple[str, list[str], list[str], int]:
    label = f"scene.renderUnits[{index}]"
    keys = {"unitId", "elementIds", "zIndex", "entry", "sharedGroupId",
            "maskDependencyUnitIds", "compositeMode", "palmierGranularity"}
    required = {"unitId", "elementIds", "zIndex", "entry", "compositeMode",
                "palmierGranularity"}
    row = _object(item, label, keys)
    _required(row, label, required)
    unit_id = _stable_id(row["unitId"], f"{label}.unitId")
    element_ids = row["elementIds"]
    if not isinstance(element_ids, list) or not element_ids \
            or len(set(element_ids)) != len(element_ids):
        raise SceneContractError(f"{label}.elementIds must be unique and non-empty")
    for ident in element_ids:
        _stable_id(ident, f"{label}.elementIds")
    z_index = row["zIndex"]
    if isinstance(z_index, bool) or not isinstance(z_index, int) \
            or not -10000 <= z_index <= 10000:
        raise SceneContractError(f"{label}.zIndex is invalid")
    _relative_html(row["entry"], f"{label}.entry")
    if "sharedGroupId" in row:
        _stable_id(row["sharedGroupId"], f"{label}.sharedGroupId")
    deps = row.get("maskDependencyUnitIds", [])
    if not isinstance(deps, list) or len(set(deps)) != len(deps):
        raise SceneContractError(f"{label}.maskDependencyUnitIds is invalid")
    for ident in deps:
        _stable_id(ident, f"{label}.maskDependencyUnitIds")
    if row["compositeMode"] not in {"normal", "screen", "multiply", "declared"}:
        raise SceneContractError(f"{label}.compositeMode is unsupported")
    if row["palmierGranularity"] not in {"scene", "unit"}:
        raise SceneContractError(f"{label}.palmierGranularity is unsupported")
    return unit_id, element_ids, deps, z_index


def _assert_acyclic(edges: dict[str, list[str]]) -> None:
    visited: set[str] = set()
    active: set[str] = set()

    def visit(node: str) -> None:
        if node in active:
            raise SceneContractError("render-unit mask dependencies contain a cycle")
        if node in visited:
            return
        active.add(node)
        for dependency in edges[node]:
            visit(dependency)
        active.remove(node)
        visited.add(node)

    for node in edges:
        visit(node)


def _render_units(value: object, element_ids: set[str]) -> None:
    if not isinstance(value, list) or not value:
        raise SceneContractError("scene.renderUnits must be a non-empty array")
    rows = [_unit_row(item, index) for index, item in enumerate(value)]
    unit_ids = [row[0] for row in rows]
    z_values = [row[3] for row in rows]
    if len(set(unit_ids)) != len(unit_ids) or len(set(z_values)) != len(z_values):
        raise SceneContractError("render unit ids and zIndex values must be unique")
    owned = [ident for row in rows for ident in row[1]]
    if len(set(owned)) != len(owned) or set(owned) != element_ids:
        raise SceneContractError("render units must own every element exactly once")
    edges = {row[0]: row[2] for row in rows}
    for unit, dependencies in edges.items():
        if unit in dependencies or any(dep not in edges for dep in dependencies):
            raise SceneContractError("render-unit mask dependency is invalid")
    _assert_acyclic(edges)


def _dependencies(value: object) -> None:
    if not isinstance(value, list):
        raise SceneContractError("scene.dependencies must be an array")
    identities: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        label = f"scene.dependencies[{index}]"
        row = _object(item, label, {"kind", "id", "sha256"})
        _required(row, label, {"kind", "id", "sha256"})
        identity = (_stable_id(row["kind"], f"{label}.kind"),
                    _stable_id(row["id"], f"{label}.id"))
        if identity in identities:
            raise SceneContractError(f"duplicate scene dependency {identity}")
        identities.add(identity)
        _digest(row["sha256"], f"{label}.sha256")


def _provenance(value: object) -> None:
    row = _object(value, "scene.provenance",
                  {"origin", "requestId", "stylePackHash"})
    _required(row, "scene.provenance", {"origin"})
    if row["origin"] not in {"operator", "autopilot", "reference-style"}:
        raise SceneContractError("scene.provenance.origin is unsupported")
    if "requestId" in row:
        _stable_id(row["requestId"], "scene.provenance.requestId")
    if "stylePackHash" in row:
        _digest(row["stylePackHash"], "scene.provenance.stylePackHash")
    if row["origin"] == "reference-style" and "stylePackHash" not in row:
        raise SceneContractError("reference-style scenes require stylePackHash")


def validate_scene(scene: object) -> dict:
    """Validate all non-template-specific SceneSpecV1 invariants."""
    row = _object(scene, "scene", _ROOT_KEYS | {"visualSources"})
    _required(row, "scene", _ROOT_KEYS)
    if row["schemaVersion"] != SCHEMA_VERSION:
        raise SceneContractError("scene.schemaVersion must be 1")
    _stable_id(row["sceneId"], "scene.sceneId")
    _positive_int(row["version"], "scene.version")
    _timing(row["timing"])
    _canvas(row["canvas"])
    if row["renderMode"] not in {
            "overlay-alpha", "takeover-opaque", "presenter-hole"}:
        raise SceneContractError("scene.renderMode is unsupported")
    _composition(row["composition"])
    from graphics.visual_source_policy import require_scene_sources
    require_scene_sources(row)
    element_ids = _elements(row["elements"])
    _render_units(row["renderUnits"], element_ids)
    if row["captionPolicy"] not in {"preserve", "suppress-overlap"}:
        raise SceneContractError("scene.captionPolicy is unsupported")
    _dependencies(row["dependencies"])
    _provenance(row["provenance"])
    canonical_json(row)
    return row

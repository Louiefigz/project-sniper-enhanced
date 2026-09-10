"""Strict manifest contract for one project-scoped HyperFrames bundle."""
from __future__ import annotations

import math
import re
from fractions import Fraction

from graphics.scene_contract import SceneContractError

# These are metadata versions, not approval of an executable render closure.
AUTHORING_HYPERFRAMES_VERSION = "0.8.31"
READABLE_HYPERFRAMES_VERSIONS = ("0.7.33", AUTHORING_HYPERFRAMES_VERSION)

_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_VARIABLE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_HTML = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*\.html$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROOT_KEYS = {
    "schemaVersion", "bundleId", "fullEntry", "unitEntries",
    "supportedCanvases", "supportedFps", "variables", "assetIds", "seed",
    "runtime",
}


def _object(value: object, label: str, allowed: set[str]) -> dict:
    if not isinstance(value, dict):
        raise SceneContractError(f"{label} must be an object")
    extras = sorted(set(value) - allowed)
    if extras:
        raise SceneContractError(f"{label} has unsupported fields: {extras}")
    return value


def _required(row: dict, label: str, required: set[str]) -> None:
    if missing := sorted(required - set(row)):
        raise SceneContractError(f"{label} is missing fields: {missing}")


def _stable_id(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) > 96 or not _ID.fullmatch(value):
        raise SceneContractError(f"{label} must be a stable id")
    return value


def _entry(value: object, label: str) -> str:
    parts = value.split("/") if isinstance(value, str) else []
    valid = isinstance(value, str) and len(value) <= 240 \
        and not value.startswith("/") and _HTML.fullmatch(value) \
        and not any(part in {"", ".", ".."} for part in parts)
    if not valid:
        raise SceneContractError(f"{label} must be a safe relative HTML path")
    return value


def _canvas(value: object, label: str) -> tuple[int, int]:
    row = _object(value, label, {"width", "height"})
    _required(row, label, {"width", "height"})
    width, height = row["width"], row["height"]
    valid = all(type(item) is int and 2 <= item <= 8192 and item % 2 == 0
                for item in (width, height))
    if not valid:
        raise SceneContractError(f"{label} dimensions must be even and <= 8192")
    return width, height


def _rational(value: object, label: str) -> tuple[int, int]:
    row = _object(value, label, {"numerator", "denominator"})
    _required(row, label, {"numerator", "denominator"})
    values = []
    for key in ("numerator", "denominator"):
        raw = row[key]
        if not isinstance(raw, str) or not re.fullmatch(r"[1-9][0-9]*", raw):
            raise SceneContractError(f"{label}.{key} must be canonical")
        values.append(int(raw))
    reduced = Fraction(values[0], values[1])
    if (reduced.numerator, reduced.denominator) != tuple(values) \
            or not 1 <= float(reduced) <= 120:
        raise SceneContractError(f"{label} must be reduced and within 1..120")
    return values[0], values[1]


def _variable(value: object, index: int) -> str:
    label = f"bundle.variables[{index}]"
    keys = {"id", "type", "required", "elementIds", "default", "values",
            "maxLength"}
    row = _object(value, label, keys)
    _required(row, label, {"id", "type", "required", "elementIds"})
    ident = row["id"]
    if not isinstance(ident, str) or not _VARIABLE.fullmatch(ident):
        raise SceneContractError(f"{label}.id is invalid")
    if row["type"] not in {"string", "number", "boolean", "color", "enum"}:
        raise SceneContractError(f"{label}.type is unsupported")
    if type(row["required"]) is not bool:
        raise SceneContractError(f"{label}.required must be boolean")
    element_ids = row["elementIds"]
    if not isinstance(element_ids, list) or not element_ids \
            or len(set(element_ids)) != len(element_ids):
        raise SceneContractError(f"{label}.elementIds must be unique and non-empty")
    for element_id in element_ids:
        _stable_id(element_id, f"{label}.elementIds")
    values = row.get("values")
    if row["type"] == "enum" and (
            not isinstance(values, list) or not values or len(values) != len(
                {repr(item) for item in values})
            or not all(isinstance(item, str) and len(item) <= 4000
                       for item in values)):
        raise SceneContractError(f"{label}.values must close the enum")
    if row["type"] != "enum" and "values" in row:
        raise SceneContractError(f"{label}.values is enum-only")
    if "maxLength" in row and (
            row["type"] != "string" or type(row["maxLength"]) is not int
            or not 1 <= row["maxLength"] <= 4000):
        raise SceneContractError(f"{label}.maxLength is invalid")
    if "default" in row:
        _variable_value(row["default"], row, f"{label}.default")
    return ident


def _variable_value(value: object, definition: dict, label: str) -> None:
    kind = definition["type"]
    number = type(value) is int \
        or type(value) is float and math.isfinite(value)
    valid = (
        kind == "boolean" and type(value) is bool
        or kind == "number" and number
        or kind in {"string", "color", "enum"} and isinstance(value, str)
    )
    if not valid:
        raise SceneContractError(f"{label} does not match {kind}")
    if kind == "color" and not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise SceneContractError(f"{label} must be #RRGGBB")
    if kind == "enum" and value not in definition["values"]:
        raise SceneContractError(f"{label} is outside the closed enum")
    if kind == "string" and len(value) > definition.get("maxLength", 4000):
        raise SceneContractError(f"{label} exceeds its maximum length")


def variable_catalog(manifest: dict) -> dict[str, dict]:
    """Manifest definitions keyed by variable id after complete validation."""
    validate_bundle_manifest(manifest)
    return {row["id"]: row for row in manifest["variables"]}


def validate_variable_values(values: object, manifest: dict) -> dict:
    """Require exact declared variables and their manifest-owned value types."""
    if not isinstance(values, dict):
        raise SceneContractError("scene variables must be an object")
    catalog = variable_catalog(manifest)
    extras = sorted(set(values) - set(catalog))
    missing = sorted(key for key, row in catalog.items()
                     if row["required"] and key not in values
                     and "default" not in row)
    if extras or missing:
        raise SceneContractError(
            f"scene variables mismatch; unknown={extras}, missing={missing}")
    for key, value in values.items():
        _variable_value(value, catalog[key], f"scene variable {key}")
    return values


def resolved_variable_values(values: object, manifest: dict) -> dict:
    """Return exact render variables with manifest defaults materialized."""
    validated = validate_variable_values(values, manifest)
    catalog = variable_catalog(manifest)
    resolved = {key: row["default"] for key, row in catalog.items()
                if "default" in row}
    resolved.update(validated)
    for key, row in catalog.items():
        if row["required"] and key not in resolved:
            raise SceneContractError(f"required scene variable {key} is unresolved")
    return resolved


def validate_bundle_manifest(value: object) -> dict:
    """Validate a SceneBundleManifestV1 without trusting JSON Schema alone."""
    row = _object(value, "bundle", _ROOT_KEYS)
    _required(row, "bundle", _ROOT_KEYS)
    if row["schemaVersion"] != 1:
        raise SceneContractError("bundle.schemaVersion must be 1")
    _stable_id(row["bundleId"], "bundle.bundleId")
    full_entry = _entry(row["fullEntry"], "bundle.fullEntry")
    units = row["unitEntries"]
    if not isinstance(units, dict) or not units:
        raise SceneContractError("bundle.unitEntries must be non-empty")
    for unit_id, entry in units.items():
        _stable_id(unit_id, "bundle unit id")
        _entry(entry, f"bundle.unitEntries.{unit_id}")
    if full_entry in units.values() or len(set(units.values())) != len(units):
        raise SceneContractError("bundle entries must be distinct")
    canvases = row["supportedCanvases"]
    rates = row["supportedFps"]
    if not isinstance(canvases, list) or not canvases \
            or not isinstance(rates, list) or not rates:
        raise SceneContractError("bundle canvas/FPS support cannot be empty")
    if len(set(_canvas(item, f"bundle canvas {index}")
               for index, item in enumerate(canvases))) != len(canvases):
        raise SceneContractError("bundle.supportedCanvases contains duplicates")
    if len(set(_rational(item, f"bundle FPS {index}")
               for index, item in enumerate(rates))) != len(rates):
        raise SceneContractError("bundle.supportedFps contains duplicates")
    variables = row["variables"]
    if not isinstance(variables, list):
        raise SceneContractError("bundle.variables must be an array")
    ids = [_variable(item, index) for index, item in enumerate(variables)]
    if len(set(ids)) != len(ids):
        raise SceneContractError("bundle variable ids must be unique")
    assets = row["assetIds"]
    if not isinstance(assets, list) or len(set(assets)) != len(assets):
        raise SceneContractError("bundle.assetIds must be a unique array")
    for asset in assets:
        _stable_id(asset, "bundle asset id")
    if type(row["seed"]) is not int or not 0 <= row["seed"] <= 0xFFFFFFFF:
        raise SceneContractError("bundle.seed must be an unsigned 32-bit integer")
    runtime = _object(row["runtime"], "bundle.runtime",
                      {"hyperframesVersion", "gsapSha256"})
    _required(runtime, "bundle.runtime", {"hyperframesVersion", "gsapSha256"})
    if type(runtime["hyperframesVersion"]) is not str \
            or runtime["hyperframesVersion"] not in READABLE_HYPERFRAMES_VERSIONS \
            or not isinstance(runtime["gsapSha256"], str) \
            or not _SHA256.fullmatch(runtime["gsapSha256"]):
        raise SceneContractError("bundle runtime is not the released closure")
    return row

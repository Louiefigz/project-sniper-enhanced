"""Trust-anchor validation for frozen unified catalog discovery authorities."""
from __future__ import annotations

import os

from graphics.comp_capability_artifact import load_artifact
from planner.visual_plan_catalog_authority import (
    build_catalog_authority, source_set_sha256,
)
from planner.visual_plan_fields import VisualPlanContractError
from planner.visual_plan_file_pins import MAX_CATALOG_BYTES, read_json_pin

_METADATA_FIELDS = (
    "catalogId", "version", "registryPath", "registrySha256",
    "snapshotIndexPath", "snapshotIndexSha256", "snapshotLockPath",
    "snapshotLockSha256", "snapshotResourcePath", "snapshotResourceSha256",
    "capabilityPath", "capabilitySha256", "studyPath", "studySha256",
)


def load_catalog_authority(pin: dict) -> dict:
    """Re-derive and admit only the installed registry's exact unified corpus."""
    try:
        expected, metadata = build_catalog_authority(pin["version"])
    except (OSError, RuntimeError, ValueError) as exc:
        raise VisualPlanContractError(f"catalog snapshot is not admitted: {exc}") from exc
    _compare_metadata(pin, metadata)
    frozen = read_json_pin(
        {"path": pin["indexPath"], "sha256": pin["indexSha256"]},
        "catalog index", MAX_CATALOG_BYTES)
    if frozen != expected:
        raise VisualPlanContractError(
            "catalog index differs from the registry-derived unified authority")
    _compare_resource_authority(pin, frozen)
    items = frozen.get("items") if isinstance(frozen, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= 4096:
        raise VisualPlanContractError("catalog index items are invalid or unbounded")
    if source_set_sha256(items) != pin["sourceSetSha256"]:
        raise VisualPlanContractError("catalog sourceSetSha256 differs from pinned index")
    root = _source_root(items)
    if os.path.realpath(pin["sourceRootPath"]) != root:
        raise VisualPlanContractError("catalog sourceRootPath differs from admitted corpus")
    capability_rows, capability_error = load_artifact(metadata["capabilityPath"])
    return {"records": _record_aliases(items), "resources": frozen["resourceItems"],
            "sourceRootPath": root, "capabilityPath": metadata["capabilityPath"],
            "capabilitySha256": metadata["capabilitySha256"],
            "capabilityRows": capability_rows or {},
            "capabilityError": capability_error, "pin": pin}


def _compare_metadata(pin: dict, metadata: dict) -> None:
    for key in _METADATA_FIELDS:
        actual, expected = pin[key], metadata[key]
        if key.endswith("Path"):
            actual, expected = os.path.realpath(actual), os.path.realpath(expected)
        if actual != expected:
            raise VisualPlanContractError(f"catalogPin {key} differs from admitted snapshot")


def _compare_resource_authority(pin: dict, frozen: object) -> None:
    resource = read_json_pin(
        {"path": pin["resourceIndexPath"], "sha256": pin["resourceIndexSha256"]},
        "catalog resource index", MAX_CATALOG_BYTES)
    if resource != frozen:
        raise VisualPlanContractError(
            "catalog resource authority differs from unified catalog authority")
    rows = resource.get("resourceItems") if isinstance(resource, dict) else None
    if not isinstance(rows, dict) or len(rows) > 4096:
        raise VisualPlanContractError("catalog resource index items are invalid")


def _source_root(items: list[dict]) -> str:
    paths = [row.get("source", {}).get("path") for row in items
             if row.get("source", {}).get("exists")]
    if not paths or any(not isinstance(path, str) for path in paths):
        raise VisualPlanContractError("catalog source inventory is invalid")
    root = os.path.commonpath(paths)
    while not os.path.isdir(root):
        root = os.path.dirname(root)
    return os.path.realpath(root)


def _record_aliases(rows: list[dict]) -> dict[str, dict]:
    aliases: dict[str, dict] = {}
    for index, row in enumerate(rows):
        _add_record_aliases(aliases, _record_names(row, index), row)
    return aliases


def _record_names(row: object, index: int) -> set[str]:
    if not isinstance(row, dict):
        raise VisualPlanContractError(f"catalog record {index} is not an object")
    names = {row.get("id"), row.get("ref"), row.get("name")}
    names.discard(None)
    if not names or any(not isinstance(name, str) or not name for name in names):
        raise VisualPlanContractError(f"catalog record {index} lacks a stable identity")
    return names


def _add_record_aliases(aliases: dict[str, dict], names: set[str], row: dict) -> None:
    for name in names:
        if name in aliases and aliases[name] is not row:
            raise VisualPlanContractError(f"catalog identity is duplicated: {name}")
        aliases[name] = row

"""Plan a fail-closed, card-level repair for a Desktop Palmier candidate."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from fingerprints import file_sha256, json_canon
from graphics.graphics_render import (
    render_entry_at_rate as render_entry,
    timeline_padded_entry,
)
from graphics.placement_context import bind_plan_face_bbox
from palmier.checkpoint_graphics import (
    PlacementBakeContext,
    assert_reference_current,
    bake_rendered_graphic,
)
from palmier.mcp_client import PalmierError
from palmier.presenter_asset import PresenterRequest, fill_presenter_entry

_FIXED_LANES = (
    "target", "cutTrack", "punchIns", "transitions", "brollTrack", "reframe",
    "captions", "music", "audioEnhance", "audioGain", "baselineLook",
    "audioAuthorityMode", "titleCards", "faceBBoxNorm", "treatmentMap",
    "sfxTrack", "chapters",
)


@dataclass(frozen=True)
class RepairRenderContext:
    """Runtime facts needed to render one changed Desktop graphic."""

    fps: float
    cache_dir: str
    source: dict
    placement: PlacementBakeContext | None = None


def _same(left: object, right: object) -> bool:
    return json.dumps(json_canon(left), sort_keys=True, separators=(",", ":")) \
        == json.dumps(json_canon(right), sort_keys=True, separators=(",", ":"))


def _graphic_id(row: object, index: int) -> str:
    if not isinstance(row, dict):
        raise PalmierError(f"graphicsTrack[{index}] is malformed")
    value = row.get("id") or row.get("semanticBeatId")
    if not isinstance(value, str) or not value:
        raise PalmierError(
            f"graphicsTrack[{index}] needs a stable id before scoped repair")
    return value


def _graphics(plan: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    rows = plan.get("graphicsTrack") or []
    if not isinstance(rows, list):
        raise PalmierError("graphicsTrack must be a list for scoped repair")
    for index, row in enumerate(rows):
        ident = _graphic_id(row, index)
        if ident in result:
            raise PalmierError(f"duplicate scoped graphic identity {ident!r}")
        result[ident] = row
    return result


def _assert_scope(old: dict, new: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    changed = [lane for lane in _FIXED_LANES
               if not _same(old.get(lane), new.get(lane))]
    if changed:
        raise PalmierError(
            "scoped graphic repair cannot change timing/base lanes: "
            + ", ".join(changed))
    before, after = _graphics(old), _graphics(new)
    if set(before) != set(after):
        raise PalmierError(
            "adding or removing graphics requires a visual-stage rebuild")
    for ident in before:
        old_window = (before[ident].get("outStart"), before[ident].get("outEnd"))
        new_window = (after[ident].get("outStart"), after[ident].get("outEnd"))
        if not _same(old_window, new_window):
            raise PalmierError(
                f"graphic {ident!r} changed timing; scoped retime is not proven")
        structure = ("kind", "anchor", "informationForm", "chassis")
        changed_structure = [key for key in structure
                             if not _same(before[ident].get(key),
                                          after[ident].get(key))]
        if changed_structure:
            raise PalmierError(
                f"graphic {ident!r} changed structural fields "
                f"{', '.join(changed_structure)}; rebuild the visual stage")
    return before, after


def _render_payload(row: dict) -> dict:
    return {key: row.get(key) for key in
            ("kind", "anchor", "outStart", "outEnd", "spec", "faceCx",
             "placement", "faceBBoxNorm", "gazeXY", "takeoverBase")}


def validate_one_graphic_repair(old_plan: dict, new_plan: dict) -> str:
    """Require a repair plan to alter exactly one graphic pixel payload."""
    before, after = _assert_scope(old_plan, new_plan)
    ignored = {"graphicsTrack", "planVersion", "graphicsDecisions"}
    changed_lanes = [
        key for key in sorted(set(old_plan) | set(new_plan))
        if not key.startswith("_") and key not in ignored
        and not _same(old_plan.get(key), new_plan.get(key))
    ]
    if changed_lanes:
        raise PalmierError(
            "one-graphic acceptance repair changes other plan lanes: "
            + ", ".join(changed_lanes))
    changed = [
        ident for ident in sorted(after)
        if not _same(
            _render_payload(before[ident]), _render_payload(after[ident]))
    ]
    if len(changed) != 1:
        raise PalmierError(
            "live acceptance repair must change exactly one graphic")
    return changed[0]


def _placement_context(context: RepairRenderContext) -> PlacementBakeContext:
    if context.placement is None:
        raise PalmierError(
            "scoped graphic repair has no delivery placement authority")
    return context.placement


def render_changed_graphics(old_plan: dict, new_plan: dict,
                            context: RepairRenderContext) -> list[dict]:
    """Render only changed card pixels and return minimal overlay steps."""
    before, after = _assert_scope(old_plan, new_plan)
    changed = [ident for ident in after
               if not _same(_render_payload(before[ident]),
                            _render_payload(after[ident]))]
    if not changed:
        raise PalmierError("scoped repair found no changed graphic pixels")
    imports, overlays = [], []
    placement = _placement_context(context)
    for ident in changed:
        row = bind_plan_face_bbox([after[ident]], new_plan)[0]
        render_row = timeline_padded_entry(row, context.fps)
        rendered = render_entry(render_row, context.cache_dir, context.fps)
        rendered = fill_presenter_entry(PresenterRequest(
            new_plan, context.source, row, rendered, context.cache_dir))
        rendered = bake_rendered_graphic(row, rendered, placement)
        proof = rendered.get("proof")
        if not isinstance(proof, dict) or proof.get("schemaVersion") != 1:
            raise PalmierError(f"graphic {ident!r} has no rendered asset proof")
        key = f"repair-source:{ident}"
        receipt_path = rendered["path"] + ".placement.json"
        imports.append({"op": "import", "key": key,
                        "path": rendered["path"], "elementId": ident,
                        "stableIdentity": True,
                        "placementReceiptPath": receipt_path,
                        "placementReceiptHash": file_sha256(receipt_path)})
        overlays.append({
            "mediaKey": key, "elementId": ident, "stableIdentity": True,
            "startFrame": round(float(row["outStart"]) * context.fps),
            "endFrame": round(float(row["outEnd"]) * context.fps),
            "transform": {"width": 1.0, "height": 1.0,
                          "centerX": 0.5, "centerY": 0.5},
        })
    assert_reference_current(placement)
    return [*imports, {"op": "overlays", "entries": overlays}]


def _overlay_entries(steps: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for step in steps:
        if step.get("op") != "overlays":
            continue
        for row in step.get("entries") or []:
            ident = row.get("elementId") if isinstance(row, dict) else None
            if isinstance(ident, str):
                result[ident] = row
    return result


def _imports(steps: list[dict]) -> dict[str, dict]:
    return {str(row.get("key")): row for row in steps
            if row.get("op") == "import" and isinstance(row.get("key"), str)}


def _ledger_elements(ledger: object) -> dict[str, dict]:
    if not isinstance(ledger, dict) or ledger.get("schemaVersion") not in {1, 2}:
        raise PalmierError(
            "scoped repair requires a current Desktop element ledger")
    elements = ledger.get("elements")
    if not isinstance(elements, dict):
        raise PalmierError("Desktop element ledger has no elements")
    return elements


def _replacement(ident: str, overlay: dict, asset: dict,
                 current: dict) -> list[dict]:
    if current.get("status") != "current" \
            or not isinstance(current.get("clipId"), str) \
            or not isinstance(current.get("mediaRef"), str) \
            or not isinstance(current.get("trackIndex"), int):
        raise PalmierError(f"graphic {ident!r} has no current Palmier binding")
    old_path, new_path = current.get("assetPath"), asset.get("path")
    if not isinstance(old_path, str) or not isinstance(new_path, str) \
            or os.path.splitext(old_path)[1].lower() \
            != os.path.splitext(new_path)[1].lower():
        raise PalmierError(
            f"graphic {ident!r} changed alpha/opaque delivery format; "
            "rebuild the visual stage")
    import_step = {
        **asset, "key": f"repair:{ident}", "elementId": ident,
        "stableIdentity": True, "repairFor": current["clipId"],
    }
    replace = {
        "op": "replace-overlay", "lane": "graphics", "elementId": ident,
        "oldClipId": current["clipId"], "oldMediaRef": current["mediaRef"],
        "trackIndex": current["trackIndex"],
        "startFrame": overlay["startFrame"], "endFrame": overlay["endFrame"],
        "transform": overlay.get("transform"),
        "path": asset["path"], "fileHash": asset["fileHash"],
        "placementReceiptPath": asset.get("placementReceiptPath"),
        "placementReceiptHash": asset.get("placementReceiptHash"),
        "rules": [
            "import the bound asset, then add it at this exact track/window",
            "the old clip may be auto-replaced; remove it only if readback retains it",
            "do not move, resize, or regenerate unrelated timeline elements",
        ],
    }
    return [import_step, replace]


def build_graphic_repair(old_plan: dict, new_plan: dict,
                         full_steps: list[dict], ledger: object) -> list[dict]:
    """Return only changed graphic imports/replacements; reject wider edits."""
    _before, after = _assert_scope(old_plan, new_plan)
    overlays, imports = _overlay_entries(full_steps), _imports(full_steps)
    elements = _ledger_elements(ledger)
    result: list[dict] = []
    if any(ident not in after for ident in overlays):
        raise PalmierError("repair steps contain an unknown graphic identity")
    for ident, overlay in overlays.items():
        current = elements.get(ident)
        if not isinstance(current, dict):
            raise PalmierError(f"graphic {ident!r} is missing from repair bindings")
        asset = imports.get(str(overlay.get("mediaKey")))
        if not isinstance(asset, dict) or not isinstance(asset.get("fileHash"), str):
            raise PalmierError(f"graphic {ident!r} has no rendered asset receipt")
        if asset["fileHash"] == current.get("assetHash"):
            continue
        result.extend(_replacement(ident, overlay, asset, current))
    if not result:
        raise PalmierError("scoped repair found no changed rendered graphic")
    return result


def build_scoped_repair(old_plan: dict, new_plan: dict,
                        context: RepairRenderContext,
                        ledger: object) -> tuple[list[dict], str]:
    """Dispatch one narrow repair without replaying unrelated lanes."""
    if not _same(old_plan.get("persistentText"), new_plan.get("persistentText")):
        raise PalmierError(
            "persistentText is no longer an edit-plan lane; use a Palmier "
            "revision-set nativeText operation")
    rendered = render_changed_graphics(old_plan, new_plan, context)
    imports = {str(row.get("key")): row for row in rendered
               if row.get("op") == "import"}
    for row in imports.values():
        row["fileHash"] = file_sha256(row["path"])
    for step in rendered:
        for entry in step.get("entries") or []:
            asset = imports[str(entry["mediaKey"])]
            entry.update({"assetPath": asset["path"],
                          "assetHash": asset["fileHash"]})
    steps = build_graphic_repair(old_plan, new_plan, rendered, ledger)
    return steps, "changed-rendered-graphics-only"

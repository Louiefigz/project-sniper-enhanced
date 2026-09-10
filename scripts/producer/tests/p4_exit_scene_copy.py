"""Load-bearing one-unit right-copy repair for the P4 live cohort."""
from __future__ import annotations

from pathlib import Path

from graphics.scene_oracle import (
    UnitMedia,
    UnitOracleRequest,
    prove_unit_equivalence,
)
from graphics.scene_render import SceneRenderRequest, render_scene
from palmier.scene_bindings import scene_binding_delta
from planner.treatment_operations import apply_treatment_operation
from tests.p4_exit_media import cache_media, file_identity
from tests.p4_exit_scene_support import (
    SceneRunContext,
    asset_hash,
    receipt_map,
    render_package,
    scene_state,
)
from tests.scene_fixtures import fire_sparkles_scene


def _operation() -> dict:
    return {
        "schemaVersion": 1, "operation": "title.setText",
        "sceneId": "scene-045", "elementId": "right-copy",
        "variable": "rightTitle", "text": "Repaired right card copy",
        "expectedText": "Change only this card", "expectedSceneVersion": 1,
    }


def _execute(context: SceneRunContext) -> dict:
    initial_scene = fire_sparkles_scene(context.bundle.digest)
    initial = render_package(context, initial_scene, "copy-initial")
    before = cache_media(context.cache)
    left_before = file_identity(
        Path(receipt_map(initial)["unit-left"]["path"]))
    treatment = apply_treatment_operation(
        scene_state(initial_scene), _operation())
    changed_scene = treatment.state.scenes[0]
    changed = render_package(context, changed_scene, "copy-changed")
    after = cache_media(context.cache)
    forced_cache = context.root / "copy-forced-cache"
    forced_cache.mkdir()
    forced = render_package(
        context, changed_scene, "copy-forced", forced_cache)
    return {
        "initial": initial, "changedScene": changed_scene,
        "changed": changed, "forced": forced, "cacheBefore": before,
        "cacheAfter": after, "leftBefore": left_before,
        "treatment": treatment,
    }


def _measure(context: SceneRunContext, run: dict) -> dict:
    initial_rows = receipt_map(run["initial"])
    changed_rows = receipt_map(run["changed"])
    forced_rows = receipt_map(run["forced"])
    left_after = file_identity(Path(changed_rows["unit-left"]["path"]))
    delta = scene_binding_delta(
        run["initial"]["palmierBindings"],
        run["changed"]["palmierBindings"])
    scene = run["changedScene"]
    full = render_scene(SceneRenderRequest(
        scene, context.bundle, str(context.root / "copy-full-cache")))
    z_order = {row["unitId"]: row["zIndex"] for row in scene["renderUnits"]}
    units = tuple(UnitMedia(
        unit_id, z_order[unit_id], row["path"])
        for unit_id, row in changed_rows.items())
    oracle = prove_unit_equivalence(UnitOracleRequest(
        scene, full["path"], units,
        str(context.root / "copy-ordered-units.mov")))
    forced_hashes = {
        key: asset_hash(changed_rows[key]) == asset_hash(forced_rows[key])
        for key in sorted(changed_rows)
    }
    return {
        "initialRows": initial_rows, "changedRows": changed_rows,
        "forcedRows": forced_rows, "leftAfter": left_after, "delta": delta,
        "oracle": oracle, "forcedHashes": forced_hashes,
        "newMedia": sorted(set(run["cacheAfter"]) - set(run["cacheBefore"])),
    }


def _passes(run: dict, measured: dict) -> bool:
    delta, oracle = measured["delta"], measured["oracle"]
    return (
        [row["cached"] for row in run["initial"]["renderReceipts"]]
        == [False, False]
        and [row["cached"] for row in run["changed"]["renderReceipts"]]
        == [True, False]
        and [row["cached"] for row in run["forced"]["renderReceipts"]]
        == [False, False]
        and run["leftBefore"] == measured["leftAfter"]
        and len(measured["newMedia"]) == 1
        and [row["action"] for row in delta["operations"]]
        == ["replace-media"]
        and delta["operations"][0]["bindingId"].endswith("unit-right")
        and delta["preservedBindingIds"] == ["scene-045-unit-left"]
        and all(measured["forcedHashes"].values())
        and oracle["colorSsim"] >= 0.995
        and oracle["alphaSsim"] >= 0.995
    )


def _result(run: dict, measured: dict) -> dict:
    delta = measured["delta"]
    cached = lambda rows: {
        key: row["cached"] for key, row in rows.items()}
    return {
        "passed": _passes(run, measured),
        "operationReceipt": run["treatment"].receipt,
        "initialCached": cached(measured["initialRows"]),
        "changedCached": cached(measured["changedRows"]),
        "forcedCached": cached(measured["forcedRows"]),
        "leftMediaUnchanged": run["leftBefore"] == measured["leftAfter"],
        "newCacheMedia": measured["newMedia"],
        "bindingDelta": {
            "actions": [row["action"] for row in delta["operations"]],
            "bindingIds": [row["bindingId"] for row in delta["operations"]],
            "preserved": delta["preservedBindingIds"],
        },
        "forcedUnitHashesMatch": measured["forcedHashes"],
        "forcedFullOracle": measured["oracle"],
    }


def run_copy_repair(context: SceneRunContext) -> tuple[dict, dict, dict]:
    run = _execute(context)
    result = _result(run, _measure(context, run))
    return result, run["changedScene"], run["forced"]

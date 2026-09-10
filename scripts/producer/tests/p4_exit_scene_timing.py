"""Load-bearing same-duration zero-render timing move for P4."""
from __future__ import annotations

import copy
from pathlib import Path

from current_render_oracle import prove as prove_current_render
from graphics.composite_core import CompositeOptions, composite
from palmier.scene_bindings import scene_binding_delta
from planner.treatment_operations import apply_treatment_operation
from tests.p4_exit_media import ProgramSpec, cache_media, make_program
from tests.p4_exit_scene_support import (
    SceneRunContext,
    clips,
    render_package,
    scene_state,
)


def _execute(context: SceneRunContext, changed_scene: dict) -> dict:
    early = copy.deepcopy(changed_scene)
    early["timing"].update({
        "startFrame": 30, "endFrameExclusive": 210,
        "timelineMapHash": "c" * 64,
    })
    early_receipt = render_package(context, early, "timing-before")
    before = cache_media(context.cache)
    treatment = apply_treatment_operation(scene_state(early), {
        "schemaVersion": 1, "operation": "scene.move",
        "sceneId": "scene-045", "startFrame": 60,
        "endFrameExclusive": 240, "timelineMapHash": "d" * 64,
        "expectedSceneVersion": 2,
    })
    moved = treatment.state.scenes[0]
    moved_receipt = render_package(context, moved, "timing-moved")
    return {
        "earlyReceipt": early_receipt, "cacheBefore": before,
        "cacheAfter": cache_media(context.cache), "treatment": treatment,
        "moved": moved, "movedReceipt": moved_receipt,
    }


def _timeline_oracle(
    context: SceneRunContext,
    moved: dict,
    moved_receipt: dict,
    forced_media: dict,
) -> dict:
    base = context.root / "timing-base.mp4"
    make_program(base, ProgramSpec((1920, 1080), 30, 9.0))
    incremental = context.root / "timing-incremental.mp4"
    forced = context.root / "timing-forced.mp4"
    options = CompositeOptions(eof_pass=True)
    composite(str(base), clips(moved, moved_receipt),
              str(incremental), options)
    composite(str(base), clips(moved, forced_media), str(forced), options)
    return prove_current_render(
        incremental, forced, context.root / "timing-oracle.json")


def _result(run: dict, oracle: dict) -> dict:
    delta = scene_binding_delta(
        run["earlyReceipt"]["palmierBindings"],
        run["movedReceipt"]["palmierBindings"])
    cached = [row["cached"] for row in run["movedReceipt"]["renderReceipts"]]
    operations = delta["operations"]
    return {
        "passed": (
            run["treatment"].receipt["mediaReused"] is True
            and cached == [True, True]
            and run["cacheBefore"] == run["cacheAfter"]
            and [row["action"] for row in operations]
            == ["move-placement", "move-placement"]
            and oracle["passed"]
        ),
        "operationReceipt": run["treatment"].receipt,
        "unitCacheHits": cached,
        "cacheMediaUnchanged": run["cacheBefore"] == run["cacheAfter"],
        "bindingDelta": {
            "actions": [row["action"] for row in operations],
            "bindingIds": [row["bindingId"] for row in operations],
        },
        "forcedTimelineOracle": {
            "passed": oracle["passed"],
            "pictureComparison": oracle["pictureComparison"],
            "decodedAudioMatch": oracle["decodedAudioMatch"],
            "streamFactsMatch": oracle["streamFactsMatch"],
        },
    }


def run_timing_move(
    context: SceneRunContext,
    changed_scene: dict,
    forced_media: dict,
) -> dict:
    run = _execute(context, changed_scene)
    oracle = _timeline_oracle(
        context, run["moved"], run["movedReceipt"], forced_media)
    return _result(run, oracle)

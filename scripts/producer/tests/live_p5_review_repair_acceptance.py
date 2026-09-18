#!/usr/bin/env python3
"""Retain real-media 14-minute/50-scene private-review proof."""
from __future__ import annotations

import argparse
import copy
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from audio.channel_normalization import (
    observe_channel_authority,
    system_program_request,
)
from current_render_oracle import prove
from graphics.scene_render import SceneRenderRequest, render_scene
from graphics.scene_package_cli import run as run_scene_package
from graphics.scene_review_media import (
    SceneReviewMediaRequest,
    render_review_fragment,
)
from graphics.scene_review_repair_cli import run as run_review
from planner.treatment_operations import apply_treatment_operation
from tests.p4_exit_media import (
    ProgramSpec,
    file_identity,
    make_program,
    source_closure,
    toolchain,
    write_canonical,
)
from tests.p4_exit_scene_support import (
    create_context,
    scene_state,
)
from tests.p5_review_project_fixture import build_project_authorities
from tests.p5_review_evidence import (
    identity,
    receipt_summary,
    resource_delta,
    resource_snapshot,
)
from tests._build_manifest_import_closure import local_import_closure
from tests.scene_fixtures import fire_sparkles_scene

REPO = Path(__file__).parents[3]
_ENTRYPOINTS = (
    "scripts/producer/tests/live_p5_review_repair_acceptance.py",
)
_DYNAMIC_FILES = (
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/bundle.json",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/compositions/full.html",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/compositions/scene-common.js",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/compositions/scene.css",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/compositions/unit-left.html",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/compositions/unit-right.html",
    "schemas/producer/channel-normalization-receipt-v1.schema.json",
    "schemas/producer/scene-bundle-v1.schema.json",
    "schemas/producer/scene-package-v1.schema.json",
    "schemas/producer/scene-spec-v1.schema.json",
    "templates/motion/hyperframes.json",
    "templates/motion/index.html",
    "templates/motion/motion-tokens.js",
    "templates/motion/package.json",
    "templates/motion/tokens.css",
    "templates/motion/vendor/gsap/gsap.min.js",
    "templates/motion/node_modules/hyperframes/dist/cli.js",
    "scripts/producer/headless/node_isolated_user.cjs",
)
CLOSURE = tuple(sorted(
    local_import_closure(_ENTRYPOINTS).union(_DYNAMIC_FILES)))


def _package(scene: dict) -> dict:
    return {
        "schemaVersion": 1, "scene": scene,
        "publicationContext": {
            "use": "commercial", "platform": "youtube",
            "evaluatedAt": "2026-07-30T12:00:00Z",
        },
        "assets": [],
        "readability": {
            "required": False, "sourceSha256": None, "receipt": None,
        },
    }


def _operation(scene: dict) -> tuple[dict, dict]:
    result = apply_treatment_operation(scene_state(scene), {
        "schemaVersion": 1, "operation": "title.setText",
        "sceneId": "scene-045", "elementId": "right-copy",
        "variable": "rightTitle", "text": "P5 private review repair",
        "expectedText": "Change only this card", "expectedSceneVersion": 1,
    })
    return result.state.scenes[0], result.receipt


def _render_package(context: object, scene: dict, label: str) -> dict:
    package = context.root / f"{label}-package.json"
    receipt = context.root / f"{label}-receipt.json"
    write_canonical(package, _package(scene))
    return run_scene_package([
        "render", str(package),
        "--bundle-store", str(context.store),
        "--cache-dir", str(context.cache),
        "--workers", "1", "--receipt-out", str(receipt),
    ])


def _run_cli(
    root: Path, context: object, base: Path, label: str,
) -> dict:
    return run_review([
        str(root / "review-initial-package.json"),
        str(root / "review-current-package.json"),
        "--previous-project-authority",
        str(root / "previous-project-authority.json"),
        "--current-project-authority",
        str(root / "current-project-authority.json"),
        "--operation-receipt", str(root / "operation.json"),
        "--previous-render-receipt",
        str(root / "review-initial-receipt.json"),
        "--base-channel-receipt", str(root / "channel.json"),
        "--bundle-store", str(context.store),
        "--cache-dir", str(context.cache),
        "--base", str(base),
        "--review-out", str(root / f"{label}.mov"),
        "--receipt-out", str(root / f"{label}-receipt.json"),
    ])


def _forced_scene(
    context: object, scene: dict, base: Path, channel: dict,
) -> tuple[dict, Path]:
    root = context.root
    cache = root / "forced-full-scene-cache"
    cache.mkdir()
    rendered = render_scene(SceneRenderRequest(
        scene, context.bundle, str(cache)))
    control = copy.deepcopy(scene)
    control["renderUnits"] = [{
        "unitId": "unit-full-scene",
        "elementIds": [row["elementId"] for row in scene["elements"]],
        "zIndex": 10, "entry": "compositions/full.html",
        "compositeMode": "normal", "palmierGranularity": "unit",
    }]
    bindings = {
        "sceneId": scene["sceneId"],
        "entries": [{
            "unitId": "unit-full-scene",
            "media": {"path": rendered["path"]},
        }],
    }
    output = root / "forced-full-scene-window.mov"
    media = render_review_fragment(SceneReviewMediaRequest(
        control, bindings, str(base), str(output), channel))
    return {"rendered": rendered, "media": media}, output


def _oracle(left: Path, right: Path, output: Path) -> dict:
    value = prove(left, right, output)
    return {
        "passed": value["passed"],
        "decodedAudioMatch": value["decodedAudioMatch"],
        "streamFactsMatch": value["streamFactsMatch"],
        "pictureComparison": value["pictureComparison"],
        "incrementalFrames":
            value["incremental"]["streamFacts"]["video"]["decodedFrames"],
        "forcedFrames":
            value["forcedFull"]["streamFacts"]["video"]["decodedFrames"],
    }


def _elapsed(started: float) -> float:
    return round(time.monotonic() - started, 3)


def run_case(root: Path) -> dict:
    """Run first repair, replay, and independent full-scene/window oracle."""
    context = create_context(root)
    base = root / "approved-base.mov"
    started = time.monotonic()
    make_program(base, ProgramSpec((1920, 1080), 30, 840.0, "flat"))
    channel = observe_channel_authority(system_program_request(str(base))).receipt
    stage_times = {"basePreparation": _elapsed(started)}
    initial_scene = fire_sparkles_scene(context.bundle.digest)
    started = time.monotonic()
    _render_package(context, initial_scene, "review-initial")
    stage_times["initialSceneRender"] = _elapsed(started)
    current_scene, operation = _operation(initial_scene)
    write_canonical(root / "review-current-package.json", _package(current_scene))
    write_canonical(root / "operation.json", operation)
    write_canonical(root / "channel.json", channel)
    started = time.monotonic()
    project = build_project_authorities(
        context, initial_scene, current_scene, base)
    stage_times["projectAuthorityAndBaseProbe"] = _elapsed(started)
    base_before = file_identity(base)
    started = time.monotonic()
    first = _run_cli(root, context, base, "first-review")
    stage_times["firstReviewRepair"] = _elapsed(started)
    started = time.monotonic()
    replay = _run_cli(root, context, base, "replay-review")
    stage_times["replayReview"] = _elapsed(started)
    started = time.monotonic()
    forced, forced_path = _forced_scene(
        context, current_scene, base, channel)
    oracle = _oracle(
        Path(first["reviewMedia"]["output"]["path"]), forced_path,
        root / "forced-review-oracle.json")
    stage_times["forcedControlAndOracle"] = _elapsed(started)
    base_after = file_identity(base)
    evidence = {
        "project": project.evidence,
        "stageElapsedSeconds": stage_times,
        "first": receipt_summary(first), "replay": receipt_summary(replay),
        "forcedFullScene": {
            "cached": forced["rendered"]["cached"],
            "reviewIdentity": identity(forced["media"]["output"]),
            "decode": forced["media"]["decode"],
        },
        "forcedFullSceneWindowOracle": oracle,
        "approvedBaseUnchanged": base_before == base_after,
        "approvedBaseIdentity": identity(base_before),
    }
    evidence["passed"] = _passes(evidence)
    return evidence


def _passes(value: dict) -> bool:
    first, replay = value["first"], value["replay"]
    return (
        value["project"]["durationSeconds"] == 840
        and value["project"]["durationFrames"] == 25_200
        and value["project"]["sceneCount"] == 50
        and value["project"]["validatedPackageCount"] == 50
        and first["projectFanout"]["dirtySceneCount"] == 1
        and first["projectFanout"]["reusedSceneCount"] == 49
        and first["unitWork"]["logicalDirtyUnitIds"] == ["unit-right"]
        and first["unitWork"]["renderedUnitIds"] == ["unit-right"]
        and first["unitWork"]["reusedUnitIds"] == ["unit-left"]
        and first["execution"]["unitRenderCount"] == 1
        and first["execution"]["fullBaseEncodeCount"] == 0
        and first["execution"]["fullDurationOutputCount"] == 0
        and first["promotion"]["activeMutationCount"] == 0
        and first["baseUnchanged"]
        and replay["unitWork"]["renderedUnitIds"] == []
        and replay["execution"]["unitRenderCount"] == 0
        and value["forcedFullScene"]["cached"] is False
        and value["forcedFullSceneWindowOracle"]["passed"]
        and value["approvedBaseUnchanged"]
    )


def run_cohort() -> dict:
    started = time.monotonic()
    resources = resource_snapshot()
    with tempfile.TemporaryDirectory(prefix="sniper-p5-review-") as raw:
        evidence = run_case(Path(raw).resolve())
    resource_usage = resource_delta(resources, resource_snapshot())
    return {
        "schemaVersion": 1, "kind": "p5-lf14-50-scene-review-repair",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "execution": {"mode": "local-real-browser-media"},
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "resourceUsage": resource_usage,
        "sourceClosure": source_closure(REPO, CLOSURE),
        "toolchain": toolchain(), "evidence": evidence,
        "nonClaims": [
            "not universal dirty-window final-master assembly",
            "not a connected Palmier timeline mutation",
            "product-route timing is reported separately",
            "not native After Effects or Palmier parity",
        ],
        "passed": evidence["passed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args()
    value = run_cohort()
    write_canonical(args.artifact.resolve(), value)
    return 0 if value["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

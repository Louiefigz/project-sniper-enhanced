#!/usr/bin/env python3
"""Generate fresh P4 v2 catalog geometry, scene reuse, grade and refusal evidence."""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from tests._build_manifest_import_closure import local_import_closure
from tests.p4_exit_geometry_case import run_geometry_case
from tests.p4_exit_media import source_closure, toolchain, write_canonical
from tests.p4_exit_scene_cases import run_scene_cases
from tests.p4_exit_scene_support import FIXTURE
from graphics.scene_bundle import capture_bundle
from graphics.scene_executor import scene_runtime_identity
from tests.p4_exit_treatment_cases import run_treatment_cases

REPO = Path(__file__).parents[3]
HISTORICAL = 'docs/producer/command-driven-editing/contracts/p4-live-exit-closure-v1.json'
HISTORICAL_SHA256 = 'b041173e5883a9fc4304ab6e500647e452674a98f01b2cb72cfd6b7a6c9b42fc'
_ENTRYPOINTS = (
    "scripts/producer/tests/live_p4_exit_closure_acceptance.py",
)
_DECLARED_CLOSURE = (
    HISTORICAL,
    "vendor/hyperframes-catalog/catalog-index.json",
    "scripts/producer/tests/live_p4_exit_closure_acceptance.py",
    "scripts/producer/tests/p4_exit_media.py",
    "scripts/producer/tests/p4_exit_geometry_case.py",
    "scripts/producer/tests/p4_exit_scene_cases.py",
    "scripts/producer/tests/p4_exit_scene_copy.py",
    "scripts/producer/tests/p4_exit_scene_support.py",
    "scripts/producer/tests/p4_exit_scene_timing.py",
    "scripts/producer/tests/p4_exit_treatment_cases.py",
    "scripts/producer/tests/scene_fixtures.py",
    "scripts/producer/motion/transition_sfx_repair.py",
    "scripts/producer/motion/transitions.py",
    "scripts/producer/motion/baseline_look.py",
    "scripts/producer/graphics/graphics_stage.py",
    "scripts/producer/graphics/graphics_render.py",
    "scripts/producer/graphics/stage_placement.py",
    "scripts/producer/graphics/delivery_geometry.py",
    "scripts/producer/graphics/composite_core.py",
    "scripts/producer/graphics/render_cache.py",
    "scripts/producer/graphics/scene_render.py",
    "scripts/producer/graphics/scene_package_render.py",
    "scripts/producer/graphics/scene_oracle.py",
    "scripts/producer/graphics/scene_bundle.py",
    "scripts/producer/graphics/scene_executor.py",
    "scripts/producer/current_render_oracle.py",
    "scripts/producer/palmier/scene_bindings.py",
    "scripts/producer/planner/treatment_operations.py",
    "scripts/producer/planner/treatment_plan_handlers.py",
    "scripts/producer/producer_config.py",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/bundle.json",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/compositions/full.html",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/compositions/scene-common.js",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/compositions/scene.css",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/compositions/unit-left.html",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle-0831/compositions/unit-right.html",
    "templates/motion/compositions/line-swap.html",
    "vendor/hyperframes-catalog/compositions/components/line-swap.html",
    "schemas/producer/visual-source-policy-v1.json",
    "scripts/producer/tests/fixtures/fire-sparkles-bundle/bundle.json",
    "scripts/producer/tests/test_p4_exit_closure_artifact.py",
    "templates/motion/motion-tokens.js",
    "templates/motion/tokens.css",
    "templates/motion/vendor/gsap/gsap.min.js",
)
CLOSURE = tuple(sorted(
    local_import_closure(_ENTRYPOINTS).union(_DECLARED_CLOSURE)))


def runtime_identity() -> str:
    """Reuse the existing selected SDK/shared-runtime closure, with no media work."""
    return scene_runtime_identity(capture_bundle(str(FIXTURE.resolve()))).hex()


def _timed_case(prefix: str, callback: Callable[[Path], dict]) -> dict:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=prefix) as raw:
        result = callback(Path(raw).resolve())
    return {
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "evidence": result,
    }


def run_cohort() -> dict:
    """Run geometry, scene repair/reuse, and treatment cohorts separately."""
    if source_closure(REPO, (HISTORICAL,))[HISTORICAL] != HISTORICAL_SHA256:
        raise RuntimeError("historical P4 v1 receipt bytes changed")
    before, tools_before = source_closure(REPO, CLOSURE), toolchain()
    runtime_before = runtime_identity()
    geometry = _timed_case("sniper-p4-geometry-", run_geometry_case)
    scenes = _timed_case("sniper-p4-scenes-", run_scene_cases)
    treatments = _timed_case("sniper-p4-treatments-", run_treatment_cases)
    passed = (
        geometry["evidence"]["passed"]
        and scenes["evidence"]["copyRepair"]["passed"]
        and scenes["evidence"]["timingMove"]["passed"]
        and treatments["evidence"]["passed"]
    )
    if (source_closure(REPO, CLOSURE) != before or toolchain() != tools_before
            or runtime_identity() != runtime_before):
        raise RuntimeError("P4 implementation or toolchain changed during qualification")
    return {
        "schemaVersion": 2,
        "kind": "p4-live-catalog-exit-closure",
        "historicalEvidence": {"path": HISTORICAL, "sha256": HISTORICAL_SHA256},
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "execution": {
            "mode": "native-macos-real-browser-media",
            "networkDenialClaimed": False,
        },
        "sourceClosure": before,
        "toolchain": tools_before,
        "sceneRuntimeIdentity": runtime_before,
        "cohorts": {
            "catalogGeometry2xPortrait": geometry,
            "sceneIncremental": scenes,
            "treatments": treatments,
        },
        "nonClaims": [
            "not retired transition rendering or SFX picture-reuse qualification",
            "not landscape geometry, preserved-alpha or text-swap correctness qualification",
            "not ordinary render readiness, editorial approval or video delivery",
            "not a universal P5 dirty-window fragment renderer",
            "not reference-style mimic qualification",
            "not native After Effects or Palmier keyframe parity",
            "local mode makes no OS-level network-denial claim",
        ],
        "passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args()
    target = args.artifact.resolve()
    if target.exists() or target == (REPO / HISTORICAL).resolve():
        parser.error("qualification requires a new artifact path; historical evidence is immutable")
    result = run_cohort()
    write_canonical(target, result)
    print(json.dumps({
        "kind": result["kind"], "passed": result["passed"],
        "artifact": str(args.artifact.resolve()),
    }, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

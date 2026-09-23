"""Reusable exact-media fixture for scene-binding Desktop revisions."""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path

from fingerprints import plan_content_hash
from palmier.scene_binding_revision import SceneBindingRevisionInput
from palmier.scene_bindings import (
    SceneBindingInput,
    build_scene_bindings,
    scene_binding_delta,
)
from tests.scene_fixtures import bind_test_scene_source, fire_sparkles_scene

BUNDLE_HASH = "b" * 64
ANIMATION_HASH = "c" * 64


@dataclass
class SceneRevisionFixture:
    """Previous/current scene facts plus the current Desktop element ledger."""

    previous_scene: dict
    current_scene: dict
    previous_bindings: dict
    current_bindings: dict
    delta: dict
    ledger: dict
    new_right: Path

    def request(self) -> SceneBindingRevisionInput:
        plan_hash = plan_content_hash({})
        return SceneBindingRevisionInput(
            self.previous_scene, self.current_scene,
            self.previous_bindings, self.current_bindings, self.delta,
            self.ledger, "f" * 64, plan_hash, plan_hash)


def _media(root: Path, name: str, payload: bytes) -> Path:
    path = root / name
    path.write_bytes(payload)
    return path


def _receipt(path: Path, unit: str, version: int, key: str) -> dict:
    return {
        "schemaVersion": 1, "sceneId": "scene-045",
        "sceneVersion": version, "unitId": unit, "path": str(path),
        "renderKey": key, "animationMapHash": ANIMATION_HASH,
        "proof": {"asset": {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}},
    }


def _bindings(scene: dict, left: Path, right: Path) -> dict:
    receipts = (
        _receipt(left, "unit-left", scene["version"], "1" * 64),
        _receipt(right, "unit-right", scene["version"], "2" * 64),
    )
    return build_scene_bindings(SceneBindingInput(scene, receipts))


def _ledger(bindings: dict) -> dict:
    entries = {row["unitId"]: row for row in bindings["entries"]}
    return {"schemaVersion": 2, "tombstones": {}, "elements": {
        "scene-045-unit-left": {
            "status": "current", "lane": "graphics",
            "clipId": "clip-left", "mediaRef": "media-left",
            "assetHash": entries["unit-left"]["media"]["sha256"],
            "assetPath": entries["unit-left"]["media"]["path"],
            "startFrame": 1350, "endFrame": 1530, "trackIndex": 2,
            "version": 1, "generation": 1, "transform": {"opacity": 1},
        },
        "scene-045-unit-right": {
            "status": "current", "lane": "graphics",
            "clipId": "clip-right-old", "mediaRef": "media-right-old",
            "assetHash": entries["unit-right"]["media"]["sha256"],
            "assetPath": entries["unit-right"]["media"]["path"],
            "startFrame": 1350, "endFrame": 1530, "trackIndex": 3,
            "version": 1, "generation": 1, "transform": {"opacity": 1},
        },
    }}


def make_scene_revision_fixture(
    root: Path,
    new_suffix: str = ".mov",
) -> SceneRevisionFixture:
    """Create one right-unit media change while left-unit bytes stay exact."""
    left = _media(root, "left.mov", b"left-scene-unit")
    old_right = _media(root, "right-v1.mov", b"right-scene-unit-v1")
    new_right = _media(
        root, f"right-v2{new_suffix}", b"right-scene-unit-v2")
    previous_scene = fire_sparkles_scene(BUNDLE_HASH)
    current_scene = fire_sparkles_scene(
        BUNDLE_HASH, "Repaired right copy")
    current_scene["version"] = 2
    bind_test_scene_source(current_scene)
    previous = _bindings(previous_scene, left, old_right)
    current = _bindings(current_scene, left, new_right)
    return SceneRevisionFixture(
        previous_scene, current_scene, previous, current,
        scene_binding_delta(previous, current), _ledger(previous), new_right)


def moved_current(fixture: SceneRevisionFixture) -> tuple[dict, dict]:
    """Build counterevidence with media and timing changed together."""
    scene = copy.deepcopy(fixture.current_scene)
    scene["timing"]["startFrame"] += 30
    scene["timing"]["endFrameExclusive"] += 30
    scene["timing"]["timelineMapHash"] = "a" * 63 + "b"
    bind_test_scene_source(scene)
    left = Path(fixture.current_bindings["entries"][0]["media"]["path"])
    bindings = _bindings(scene, left, fixture.new_right)
    return scene, bindings

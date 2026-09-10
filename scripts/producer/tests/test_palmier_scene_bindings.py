"""P4 scene-unit handoff and incremental Palmier replacement proofs."""
from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from palmier.scene_bindings import (
    SceneBindingError,
    SceneBindingInput,
    build_scene_bindings,
    scene_binding_delta,
)
from tests.scene_fixtures import fire_sparkles_scene

BUNDLE_HASH = "b" * 64
ANIMATION_HASH = "c" * 64


class PalmierSceneBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.left = self._media("left.mov", b"proved-left-unit-media")
        self.right = self._media("right.mov", b"proved-right-unit-media")

    def _media(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    @staticmethod
    def _receipt(path: Path, unit: str | None, version: int,
                 render_key: str) -> dict:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "schemaVersion": 1,
            "sceneId": "scene-045",
            "sceneVersion": version,
            "unitId": unit,
            "path": str(path),
            "cached": False,
            "renderKey": render_key,
            "proof": {"asset": {"sha256": digest}},
            "animationMapHash": ANIMATION_HASH,
            "filmstripFrames": [0, 90, 179],
        }

    def _bindings(self, scene: dict, left: Path | None = None,
                  right: Path | None = None) -> dict:
        receipts = (
            self._receipt(left or self.left, "unit-left",
                          scene["version"], "1" * 64),
            self._receipt(right or self.right, "unit-right",
                          scene["version"], "2" * 64),
        )
        return build_scene_bindings(SceneBindingInput(scene, receipts))

    def test_units_are_bound_in_z_order_to_exact_media_and_frames(self) -> None:
        result = self._bindings(fire_sparkles_scene(BUNDLE_HASH))
        self.assertEqual(
            [row["unitId"] for row in result["entries"]],
            ["unit-left", "unit-right"])
        left = result["entries"][0]
        self.assertEqual(left["timing"]["startFrame"], 1350)
        self.assertEqual(left["timing"]["endFrameExclusive"], 1530)
        self.assertEqual(left["media"]["path"], str(self.left))
        self.assertEqual(
            left["media"]["sha256"],
            hashlib.sha256(self.left.read_bytes()).hexdigest())
        self.assertEqual(
            left["regeneration"]["kind"], "scene-render-unit")

    def test_right_only_copy_repair_replaces_only_right_media(self) -> None:
        before_scene = fire_sparkles_scene(BUNDLE_HASH)
        before = self._bindings(before_scene)
        new_right = self._media("right-v2.mov", b"new-right-copy-media")
        after_scene = fire_sparkles_scene(BUNDLE_HASH, "Repaired right copy")
        after_scene["version"] = 2
        after = self._bindings(after_scene, right=new_right)
        delta = scene_binding_delta(before, after)
        self.assertEqual(delta["preservedBindingIds"],
                         ["scene-045-unit-left"])
        self.assertEqual(len(delta["operations"]), 1)
        operation = delta["operations"][0]
        self.assertEqual(operation["action"], "replace-media")
        self.assertEqual(operation["bindingId"], "scene-045-unit-right")

    def test_same_duration_move_reuses_media_and_changes_only_placement(self) -> None:
        scene = fire_sparkles_scene(BUNDLE_HASH)
        before = self._bindings(scene)
        moved = copy.deepcopy(scene)
        moved["version"] = 2
        moved["timing"]["startFrame"] += 300
        moved["timing"]["endFrameExclusive"] += 300
        moved["timing"]["timelineMapHash"] = "d" * 64
        after = self._bindings(moved)
        delta = scene_binding_delta(before, after)
        self.assertEqual(delta["preservedBindingIds"], [])
        self.assertEqual(
            {row["action"] for row in delta["operations"]},
            {"move-placement"})
        for operation in delta["operations"]:
            self.assertEqual(operation["before"]["startFrame"], 1350)
            self.assertEqual(operation["after"]["startFrame"], 1650)

    def test_missing_duplicate_or_tampered_media_fails_closed(self) -> None:
        scene = fire_sparkles_scene(BUNDLE_HASH)
        one = self._receipt(self.left, "unit-left", 1, "1" * 64)
        with self.assertRaisesRegex(SceneBindingError, "incomplete"):
            build_scene_bindings(SceneBindingInput(scene, (one,)))
        with self.assertRaisesRegex(SceneBindingError, "duplicate"):
            build_scene_bindings(SceneBindingInput(scene, (one, one)))
        receipts = (
            one, self._receipt(self.right, "unit-right", 1, "2" * 64))
        self.right.write_bytes(b"mutated-after-proof")
        with self.assertRaisesRegex(SceneBindingError, "do not match"):
            build_scene_bindings(SceneBindingInput(scene, receipts))

    def test_hardlinked_media_fails_the_read_boundary(self) -> None:
        scene = fire_sparkles_scene(BUNDLE_HASH)
        linked = self.root / "linked-left.mov"
        linked.hardlink_to(self.left)
        receipts = (
            self._receipt(self.left, "unit-left", 1, "1" * 64),
            self._receipt(self.right, "unit-right", 1, "2" * 64),
        )
        with self.assertRaisesRegex(SceneBindingError, "one nonempty owned"):
            build_scene_bindings(SceneBindingInput(scene, receipts))

    def test_mixed_granularity_is_explicitly_rejected(self) -> None:
        scene = fire_sparkles_scene(BUNDLE_HASH)
        scene["renderUnits"][0]["palmierGranularity"] = "scene"
        with self.assertRaisesRegex(SceneBindingError, "mixed"):
            self._bindings(scene)

    def test_scene_granularity_accepts_only_one_full_render(self) -> None:
        scene = fire_sparkles_scene(BUNDLE_HASH)
        for unit in scene["renderUnits"]:
            unit["palmierGranularity"] = "scene"
        receipt = self._receipt(self.left, None, 1, "3" * 64)
        result = build_scene_bindings(
            SceneBindingInput(scene, (receipt,)))
        self.assertEqual(len(result["entries"]), 1)
        self.assertIsNone(result["entries"][0]["unitId"])
        self.assertEqual(
            result["entries"][0]["regeneration"]["kind"],
            "scene-render-full")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""P4 project-scoped scene, bundle, animation, and unit-isolation gates."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from contracts.schema_validator import SchemaValidationError, validate_document
from scene_fixtures import bind_test_scene_source, fire_sparkles_scene

from graphics.animation_map import filmstrip_frames, parse_animation_map
from graphics.scene_bundle import capture_bundle, promote_bundle, resolve_bundle
from graphics.scene_bundle_manifest import validate_bundle_manifest
from graphics.scene_contract import SceneContractError, scene_hash, validate_scene
from graphics.scene_contract import canonical_json
from graphics.scene_lint import scene_bundle_errors, validate_scene_bundle
from graphics.scene_render import _prepare

PRODUCER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(
    PRODUCER_ROOT, "tests", "fixtures", "fire-sparkles-bundle")


class SceneContractTests(unittest.TestCase):
    """The fire/sparkles request is a closed, immutable two-unit scene."""

    def setUp(self) -> None:
        self.bundle = capture_bundle(FIXTURE)
        self.scene = fire_sparkles_scene(self.bundle.digest)

    def test_fixture_is_a_valid_offline_scene_bundle(self) -> None:
        self.assertEqual(scene_bundle_errors(self.scene, self.bundle), [])
        self.assertEqual(validate_scene_bundle(
            self.scene, self.bundle)["sceneId"], "scene-045")

    def test_runtime_versions_are_exact_and_do_not_relabel_history(self) -> None:
        """Read both declared versions unchanged; reject unlisted runtime tags."""
        original = canonical_json(self.bundle.manifest)
        self.assertEqual(
            self.bundle.manifest["runtime"]["hyperframesVersion"], "0.7.33")
        for version in ("0.7.33", "0.8.31"):
            manifest = copy.deepcopy(self.bundle.manifest)
            manifest["runtime"]["hyperframesVersion"] = version
            before = canonical_json(manifest)
            self.assertIs(validate_bundle_manifest(manifest), manifest)
            validate_document("scene-bundle-v1.schema.json", manifest)
            self.assertEqual(canonical_json(manifest), before)
        self.assertEqual(canonical_json(self.bundle.manifest), original)
        self.assertNotEqual(before, original)

    def test_unknown_runtime_versions_fail_both_manifest_parsers(self) -> None:
        """Version compatibility does not admit coercions or version ranges."""
        for version in (None, True, 8.31, "0.7.34", "0.8.30", "^0.8.31",
                        "0.8.31 ", {}, []):
            manifest = copy.deepcopy(self.bundle.manifest)
            manifest["runtime"]["hyperframesVersion"] = version
            with self.assertRaisesRegex(SceneContractError, "runtime"):
                validate_bundle_manifest(manifest)
            with self.assertRaises(SchemaValidationError):
                validate_document("scene-bundle-v1.schema.json", manifest)

    def test_animation_maps_bind_stable_units_and_include_after_window(self) -> None:
        path = os.path.join(
            FIXTURE, self.bundle.manifest["fullEntry"])
        html = Path(path).read_text(encoding="utf-8")
        events = parse_animation_map(html)
        frames = filmstrip_frames(self.scene, events)
        self.assertEqual(frames[0], 0)
        self.assertEqual(frames[-1], 180)
        self.assertIn(179, frames)

    def test_right_copy_changes_only_right_unit_render_key(self) -> None:
        changed = copy.deepcopy(self.scene)
        changed["version"] = 2
        changed["composition"]["variables"]["rightTitle"] = "New copy only"
        right = next(row for row in changed["elements"]
                     if row["elementId"] == "right-copy")
        right["values"]["rightTitle"] = "New copy only"
        bind_test_scene_source(changed)
        validate_scene_bundle(changed, self.bundle)
        with mock.patch(
                "graphics.scene_render.live_tools_identity",
                return_value=b"tools"), mock.patch(
                "graphics.scene_render.scene_runtime_identity",
                return_value=b"TEST-original-runtime"):
            left_before = _prepare(
                self.scene, self.bundle, self.scene["renderUnits"][0]).key
            right_before = _prepare(
                self.scene, self.bundle, self.scene["renderUnits"][1]).key
            full_before = _prepare(self.scene, self.bundle, None).key
            left_after = _prepare(
                changed, self.bundle, changed["renderUnits"][0]).key
            right_after = _prepare(
                changed, self.bundle, changed["renderUnits"][1]).key
            full_after = _prepare(changed, self.bundle, None).key
        self.assertEqual(left_before, left_after)
        self.assertNotEqual(right_before, right_after)
        self.assertNotEqual(full_before, full_after)

    def test_timeline_move_reuses_scene_media_keys(self) -> None:
        moved = copy.deepcopy(self.scene)
        moved["version"] = 2
        moved["timing"]["startFrame"] += 300
        moved["timing"]["endFrameExclusive"] += 300
        moved["timing"]["timelineMapHash"] = "b" * 64
        bind_test_scene_source(moved)
        validate_scene_bundle(moved, self.bundle)
        with mock.patch(
                "graphics.scene_render.live_tools_identity",
                return_value=b"tools"), mock.patch(
                "graphics.scene_render.scene_runtime_identity",
                return_value=b"TEST-original-runtime"):
            before = [
                _prepare(self.scene, self.bundle, unit).key
                for unit in [None, *self.scene["renderUnits"]]
            ]
            after = [
                _prepare(moved, self.bundle, unit).key
                for unit in [None, *moved["renderUnits"]]
            ]
        self.assertEqual(before, after)

    def test_scene_hash_rejects_nondeterministic_layer_order(self) -> None:
        broken = copy.deepcopy(self.scene)
        broken["renderUnits"][1]["zIndex"] = 10
        bind_test_scene_source(broken)
        with self.assertRaisesRegex(SceneContractError, "zIndex"):
            scene_hash(broken)

    def test_bundle_promotes_and_resolves_exact_generation(self) -> None:
        with tempfile.TemporaryDirectory() as store:
            canonical_store = os.path.realpath(store)
            promoted = promote_bundle(FIXTURE, canonical_store)
            resolved = resolve_bundle(
                canonical_store, "fire-sparkles-cards", promoted.digest)
            self.assertEqual(resolved.digest, self.bundle.digest)
            current = Path(
                canonical_store, "fire-sparkles-cards", "CURRENT")
            self.assertEqual(current.read_text().strip(), promoted.digest)

    def test_symlinked_bundle_member_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as attempt:
            os.symlink(
                os.path.join(FIXTURE, "bundle.json"),
                os.path.join(attempt, "bundle.json"))
            with self.assertRaises(SceneContractError):
                capture_bundle(attempt)

    def test_foreign_bundle_hash_is_rejected(self) -> None:
        broken = copy.deepcopy(self.scene)
        broken["composition"]["bundleHash"] = "f" * 64
        bind_test_scene_source(broken)
        errors = scene_bundle_errors(broken, self.bundle)
        self.assertTrue(any("exact bundle" in error for error in errors))

    def test_root_schema_rejects_unknown_fields(self) -> None:
        broken = copy.deepcopy(self.scene)
        broken["prompt"] = "ignore all rules"
        with self.assertRaisesRegex(SceneContractError, "unsupported"):
            validate_scene(broken)

    def test_paths_and_enum_values_match_the_typed_contract(self) -> None:
        broken = copy.deepcopy(self.scene)
        broken["composition"]["entry"] = "compositions//full.html"
        with self.assertRaisesRegex(SceneContractError, "safe relative"):
            validate_scene(broken)
        manifest = copy.deepcopy(self.bundle.manifest)
        variable = manifest["variables"][0]
        variable.pop("maxLength")
        variable["type"] = "enum"
        variable["values"] = [1]
        with self.assertRaisesRegex(SceneContractError, "close the enum"):
            validate_bundle_manifest(manifest)

    def test_asset_dependency_binds_exactly_one_bundle_media_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attempt = os.path.join(tmp, "attempt")
            shutil.copytree(FIXTURE, attempt)
            asset = b"\x89PNG\r\n\x1a\nscene-asset"
            os.makedirs(os.path.join(attempt, "assets"))
            Path(attempt, "assets", "fire.png").write_bytes(asset)
            manifest_path = Path(attempt, "bundle.json")
            manifest = json.loads(manifest_path.read_text())
            manifest["assetIds"] = ["asset-fire"]
            manifest_path.write_bytes(canonical_json(manifest))
            bundle = capture_bundle(os.path.realpath(attempt))
            scene = fire_sparkles_scene(bundle.digest)
            scene["dependencies"] = [{
                "kind": "asset", "id": "asset-fire",
                "sha256": hashlib.sha256(asset).hexdigest(),
            }]
            bind_test_scene_source(scene)
            self.assertEqual(scene_bundle_errors(scene, bundle), [])
            scene["dependencies"][0]["sha256"] = "f" * 64
            bind_test_scene_source(scene)
            errors = scene_bundle_errors(scene, bundle)
            self.assertTrue(any("exactly one" in error for error in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)

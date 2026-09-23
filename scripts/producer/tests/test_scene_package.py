"""P4 exact package admission, rendering, and Palmier readback tests."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from graphics.scene_bundle import promote_bundle
from graphics.scene_catalog import CatalogSceneRequest, wrap_catalog_scene
from graphics.scene_contract import SceneContractError, canonical_json
from graphics.scene_package_cli import run
from graphics.scene_package_contract import resolve_scene_package
from graphics.scene_package_render import (
    ScenePackageRenderRequest,
    render_scene_package,
)
from tests.scene_fixtures import fire_sparkles_scene

FIXTURE = Path(__file__).parent / "fixtures" / "fire-sparkles-bundle"


def _package(scene: dict) -> dict:
    return {
        "schemaVersion": 1, "scene": scene,
        "publicationContext": {
            "use": "commercial", "platform": "youtube",
            "evaluatedAt": "2026-07-29T12:00:00Z",
        },
        "assets": [],
        "readability": {
            "required": False, "sourceSha256": None, "receipt": None,
        },
    }


def _catalog_scene() -> dict:
    return wrap_catalog_scene(CatalogSceneRequest(
        entry={
            "kind": "chart-story", "anchor": "own-screen",
            "outStart": 0.0, "outEnd": 0.8,
            "spec": {
                "data": "12, 28", "labels": "Before,After", "type": "bars", "emphasize": 1, "unit": "%",
            },
        },
        scene_id="scene-catalog-wash",
        timing={
            "startFrame": 0, "endFrameExclusive": 24,
            "fps": {"numerator": "30", "denominator": "1"},
            "timelineMapHash": "a" * 64,
        },
        canvas={"width": 1920, "height": 1080},
        provenance={"origin": "operator", "requestId": "request-wash"},
    ))


class ScenePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = self.root / "bundles"
        self.store.mkdir()
        self.bundle = promote_bundle(
            str(FIXTURE.resolve()), str(self.store), select_current=False)
        self.scene = fire_sparkles_scene(self.bundle.digest)

    def _package_file(self, value: dict) -> Path:
        path = self.root / "scene-package.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def _media(self, name: str, content: bytes) -> Path:
        path = self.root / name
        path.write_bytes(content)
        return path

    @staticmethod
    def _receipt(scene: dict, path: Path, unit: str, key: str) -> dict:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "schemaVersion": 1, "sceneId": scene["sceneId"],
            "sceneVersion": scene["version"], "unitId": unit,
            "path": str(path), "cached": False, "renderKey": key * 64,
            "proof": {"asset": {"sha256": digest}},
            "animationMapHash": "c" * 64,
            "filmstripFrames": [0, 90, 179],
        }

    def test_project_resolution_uses_hash_not_current_pointer(self) -> None:
        current = self.store / self.bundle.manifest["bundleId"] / "CURRENT"
        self.assertFalse(current.exists())
        current.write_text("f" * 64 + "\n", encoding="ascii")
        resolved = resolve_scene_package(_package(self.scene), str(self.store))
        self.assertEqual(resolved.bundle.digest, self.bundle.digest)
        self.assertEqual(
            resolved.source_contract["bundleHash"], self.bundle.digest)

    def test_readability_and_publication_evidence_fail_closed(self) -> None:
        missing = _package(self.scene)
        missing["readability"]["required"] = True
        with self.assertRaisesRegex(SceneContractError, "incomplete"):
            resolve_scene_package(missing, str(self.store))
        timezone_free = _package(self.scene)
        timezone_free["publicationContext"]["evaluatedAt"] = \
            "2026-07-29T12:00:00"
        with self.assertRaisesRegex(SceneContractError, "timezone"):
            resolve_scene_package(timezone_free, str(self.store))

    def test_validate_and_package_commands_emit_canonical_receipts(self) -> None:
        source = self._package_file(_package(self.scene))
        args = [str(source), "--bundle-store", str(self.store)]
        validated = run(["validate", *args])
        self.assertEqual(validated["kind"], "scene-package-admission")
        output = self.root / "admission.json"
        packaged = run(["package", *args, "--receipt-out", str(output)])
        self.assertEqual(output.read_bytes(), canonical_json(packaged) + b"\n")
        with self.assertRaisesRegex(SceneContractError, "unused filename"):
            run(["package", *args, "--receipt-out", str(output)])

    def test_project_render_projects_and_reobserves_exact_units(self) -> None:
        resolved = resolve_scene_package(_package(self.scene), str(self.store))
        left = self._media("left.mov", b"left-render")
        right = self._media("right.mov", b"right-render")
        receipts = [
            self._receipt(self.scene, left, "unit-left", "1"),
            self._receipt(self.scene, right, "unit-right", "2"),
        ]
        cache = self.root / "cache"
        cache.mkdir()
        with mock.patch(
                "graphics.scene_package_render.render_scene_units",
                return_value=receipts) as renderer:
            result = render_scene_package(ScenePackageRenderRequest(
                resolved, str(cache), workers=2))
        renderer.assert_called_once()
        self.assertEqual(result["kind"], "scene-package-render")
        self.assertEqual(
            [row["unitId"] for row in result["palmierBindings"]["entries"]],
            ["unit-left", "unit-right"])
        self.assertEqual(
            result["palmierBindings"]["entries"][0]["media"]
            ["animationMapHash"], "c" * 64)

    def test_project_bundle_mutation_after_resolution_blocks_render(self) -> None:
        resolved = resolve_scene_package(_package(self.scene), str(self.store))
        entry = Path(resolved.bundle.path) / resolved.bundle.manifest["fullEntry"]
        entry.write_text(
            entry.read_text(encoding="utf-8") + "\n<!-- changed -->",
            encoding="utf-8")
        cache = self.root / "mutated-cache"
        cache.mkdir()
        with self.assertRaisesRegex(SceneContractError, "changed"):
            render_scene_package(ScenePackageRenderRequest(
                resolved, str(cache)))

    def test_catalog_render_uses_catalog_motion_identity(self) -> None:
        scene = _catalog_scene()
        resolved = resolve_scene_package(_package(scene), None)
        media = self._media("catalog.mp4", b"catalog-render")
        digest = hashlib.sha256(media.read_bytes()).hexdigest()
        receipt = {
            "schemaVersion": 1, "sceneId": scene["sceneId"],
            "sceneVersion": scene["version"], "unitId": None,
            "path": str(media), "cached": False, "renderKey": "1" * 64,
            "proof": {"asset": {"sha256": digest}},
            "catalogSourceHash":
                resolved.source_contract["catalogSourceHash"],
            "motionContractHash":
                resolved.source_contract["motionContractHash"],
        }
        cache = self.root / "catalog-cache"
        cache.mkdir()
        with mock.patch(
                "graphics.scene_package_render.render_catalog_scene",
                return_value=receipt):
            result = render_scene_package(ScenePackageRenderRequest(
                resolved, str(cache)))
        media_binding = result["palmierBindings"]["entries"][0]["media"]
        self.assertEqual(
            set(media_binding),
            {"path", "sha256", "renderKey",
             "catalogSourceHash", "motionContractHash"})
        receipt["catalogSourceHash"] = "f" * 64
        with mock.patch(
                "graphics.scene_package_render.render_catalog_scene",
                return_value=receipt):
            with self.assertRaisesRegex(SceneContractError, "source contract"):
                render_scene_package(ScenePackageRenderRequest(
                    resolved, str(cache)))


if __name__ == "__main__":
    unittest.main(verbosity=2)

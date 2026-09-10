"""Opt-in real-browser acceptance for the production ScenePackageV1 CLI."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from graphics.scene_bundle import promote_bundle
from graphics.scene_contract import canonical_json
from graphics.scene_package_cli import run
from graphics.render_tools import resolve_tools
from tests.scene_fixtures import fire_sparkles_scene

FIXTURE = Path(__file__).parent / "fixtures" / "fire-sparkles-bundle"


@unittest.skipUnless(
    os.environ.get("RUN_P4_SCENE_PACKAGE_TESTS") == "1",
    "set RUN_P4_SCENE_PACKAGE_TESTS=1 for real HyperFrames package render",
)
class LiveScenePackageCliAcceptance(unittest.TestCase):
    """The same package reference survives every production consumer."""

    def test_fire_sparkles_package_renders_and_reads_back_units(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            store, cache = root / "bundles", root / "cache"
            store.mkdir()
            cache.mkdir()
            bundle = promote_bundle(
                str(FIXTURE.resolve()), str(store), select_current=False)
            scene = fire_sparkles_scene(bundle.digest)
            package = {
                "schemaVersion": 1,
                "scene": scene,
                "publicationContext": {
                    "use": "commercial", "platform": "youtube",
                    "evaluatedAt": "2026-07-29T12:00:00Z",
                },
                "assets": [],
                "readability": {
                    "required": False,
                    "sourceSha256": None,
                    "receipt": None,
                },
            }
            package_path = root / "scene-package.json"
            package_path.write_bytes(canonical_json(package) + b"\n")
            receipt_path = root / "scene-render-receipt.json"
            result = run([
                "render", str(package_path),
                "--bundle-store", str(store),
                "--cache-dir", str(cache),
                "--workers", "2",
                "--receipt-out", str(receipt_path),
            ])
            self.assertEqual(
                receipt_path.read_bytes(), canonical_json(result) + b"\n")
            self.assertEqual(result["kind"], "scene-package-render")
            self.assertEqual(
                [row["unitId"] for row in result["renderReceipts"]],
                ["unit-left", "unit-right"])
            self.assertEqual(
                [row["unitId"]
                 for row in result["palmierBindings"]["entries"]],
                ["unit-left", "unit-right"])
            self.assertEqual(
                result["admission"]["sourceContract"]["bundleHash"],
                bundle.digest)
            tools = resolve_tools()
            for row in result["renderReceipts"]:
                decoded = subprocess.run([
                    tools["ffmpeg"], "-nostdin", "-v", "error", "-xerror",
                    "-i", row["path"], "-map", "0:v:0", "-f", "null", "-",
                ], stdin=subprocess.DEVNULL, capture_output=True, text=True)
                self.assertEqual(decoded.returncode, 0, decoded.stderr[-500:])
                self.assertEqual(row["proof"]["decode"]["decoded"], True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

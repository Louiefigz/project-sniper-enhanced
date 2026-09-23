"""P4 AssetRecord-to-scene dependency and external sandbox admission tests."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from graphics.scene_catalog import CatalogSceneRequest, wrap_catalog_scene
from graphics.scene_package_assets import admit_package_assets
from graphics.scene_package_contract import (
    ResolvedScenePackage,
    resolve_scene_package,
)
from tests.scene_fixtures import fire_sparkles_scene


def _record(path: Path, digest: str) -> dict:
    return {
        "schemaVersion": 1, "assetId": "fire-texture",
        "sha256": digest, "sizeBytes": path.stat().st_size,
        "mime": "image/png", "origin": "approved-library",
        "acquiredAt": "2026-07-29T12:00:00Z",
        "rights": {
            "license": "internal-library-v1",
            "allowedUses": ["commercial"],
            "allowedPlatforms": ["youtube"],
            "consent": "not-applicable", "attributionRequired": False,
        },
        "media": {"width": 1, "height": 1, "hasAlpha": True},
        "provenance": {"source": "library/fire-texture.png"},
        "publicationDisposition": "approved",
    }


class ScenePackageAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.snapshot_store = self.root / "snapshots"
        self.snapshot_store.mkdir()
        self.blob = self.root / "fire.png"
        self.blob.write_bytes(b"\x89PNG\r\n\x1a\nproved")
        self.digest = hashlib.sha256(self.blob.read_bytes()).hexdigest()

    def _resolved(self, member: str | None = "media/fire.png"
                  ) -> ResolvedScenePackage:
        scene = fire_sparkles_scene("b" * 64)
        scene["dependencies"] = [{
            "kind": "asset", "id": "fire-texture", "sha256": self.digest,
        }]
        record = _record(self.blob, self.digest)
        package = {
            "schemaVersion": 1, "scene": scene,
            "publicationContext": {
                "use": "commercial", "platform": "youtube",
                "evaluatedAt": "2026-07-29T12:00:00Z",
            },
            "assets": [{
                "record": record, "blobPath": str(self.blob),
                "bundleMember": member,
            }],
            "readability": {
                "required": False, "sourceSha256": None, "receipt": None,
            },
        }
        source = {
            "type": "project", "bundleId": "fire-sparkles-cards",
            "bundleHash": "b" * 64, "bundleFileSetHash": "c" * 64,
            "bundleFiles": [{
                "path": "media/fire.png", "sha256": self.digest,
                "sizeBytes": self.blob.stat().st_size,
            }],
        }
        return ResolvedScenePackage(
            package, scene, "d" * 64, source, None, None)

    def _probe(self) -> dict:
        return {
            "schemaVersion": 1, "policy": "test",
            "snapshot": {
                "path": str(self.blob), "sha256": self.digest,
                "sizeBytes": self.blob.stat().st_size,
            },
            "decoded": {"decoded": True},
        }

    def _catalog_resolved(self, blob: Path,
                          source_claim: str) -> ResolvedScenePackage:
        scene = wrap_catalog_scene(CatalogSceneRequest(
            entry={
                "kind": "ui-focus-zoom", "anchor": "own-screen",
                "outStart": 0.0, "outEnd": 0.8,
                "spec": {"image": "assets/sample-screen.png", "zoomAt": 0.2},
            },
            scene_id="scene-logo",
            timing={
                "startFrame": 0, "endFrameExclusive": 24,
                "fps": {"numerator": "30", "denominator": "1"},
                "timelineMapHash": "a" * 64,
            },
            canvas={"width": 1920, "height": 1080},
            provenance={"origin": "operator", "requestId": "request-logo"},
        ))
        dependency = scene["dependencies"][0]
        data = blob.read_bytes()
        record = {
            "schemaVersion": 1, "assetId": dependency["id"],
            "sha256": hashlib.sha256(data).hexdigest(),
            "sizeBytes": len(data), "mime": "image/png",
            "origin": "approved-library",
            "acquiredAt": "2026-07-29T12:00:00Z",
            "rights": {
                "license": "internal-library-v1",
                "allowedUses": ["commercial"],
                "allowedPlatforms": ["youtube"],
                "consent": "not-applicable",
                "attributionRequired": False,
            },
            "media": {"width": 512, "height": 512, "hasAlpha": True},
            "provenance": {"source": source_claim},
            "publicationDisposition": "approved",
        }
        package = {
            "schemaVersion": 1, "scene": scene,
            "publicationContext": {
                "use": "commercial", "platform": "youtube",
                "evaluatedAt": "2026-07-29T12:00:00Z",
            },
            "assets": [{
                "record": record, "blobPath": str(blob),
                "bundleMember": None,
            }],
            "readability": {
                "required": False, "sourceSha256": None, "receipt": None,
            },
        }
        return resolve_scene_package(package, None)

    def test_exact_member_rights_bytes_and_sandbox_are_aggregated(self) -> None:
        with mock.patch(
                "graphics.scene_package_assets.admit_external_media",
                return_value=self._probe()) as probe:
            result = admit_package_assets(
                self._resolved(), str(self.snapshot_store))
        probe.assert_called_once_with(str(self.blob), str(self.snapshot_store))
        self.assertEqual(result[0]["bundleMember"], "media/fire.png")
        self.assertEqual(result[0]["sha256"], self.digest)
        self.assertIn("externalMediaReceiptHash", result[0])

    def test_missing_or_mismatched_member_fails_closed(self) -> None:
        with self.assertRaisesRegex(Exception, "explicit bundle member"):
            admit_package_assets(
                self._resolved(None), str(self.snapshot_store))
        resolved = self._resolved("media/other.png")
        with self.assertRaisesRegex(Exception, "exactly one"):
            admit_package_assets(resolved, str(self.snapshot_store))

    def test_probe_must_bind_exact_bytes_and_successful_decode(self) -> None:
        wrong = self._probe()
        wrong["snapshot"]["sha256"] = "f" * 64
        with mock.patch(
                "graphics.scene_package_assets.admit_external_media",
                return_value=wrong):
            with self.assertRaisesRegex(Exception, "does not bind"):
                admit_package_assets(
                    self._resolved(), str(self.snapshot_store))

    def test_catalog_asset_requires_the_exact_resolved_selector_source(self) -> None:
        source = Path(__file__).resolve().parents[3] \
            / "templates/motion/assets/sample-screen.png"
        blob = self.root / "screen-approved.png"
        blob.write_bytes(source.read_bytes())
        resolved = self._catalog_resolved(blob, str(source))
        digest = hashlib.sha256(blob.read_bytes()).hexdigest()
        receipt = {
            "snapshot": {
                "path": str(blob), "sha256": digest,
                "sizeBytes": blob.stat().st_size,
            },
            "decoded": {"decoded": True},
        }
        with mock.patch(
                "graphics.scene_package_assets.admit_external_media",
                return_value=receipt):
            admitted = admit_package_assets(
                resolved, str(self.snapshot_store))
        self.assertIsNone(admitted[0]["bundleMember"])
        mismatched = self._catalog_resolved(
            blob, str(self.root / "unapproved-selector.png"))
        with self.assertRaisesRegex(Exception, "resolved selector"):
            admit_package_assets(mismatched, str(self.snapshot_store))


if __name__ == "__main__":
    unittest.main(verbosity=2)

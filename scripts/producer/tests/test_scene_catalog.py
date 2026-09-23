"""Catalog compositions enter the same typed SceneSpec authority."""
from __future__ import annotations

import unittest
from unittest import mock

from graphics.scene_catalog import (
    CatalogSceneRequest,
    catalog_scene_contract,
    render_catalog_scene,
    wrap_catalog_scene,
)
from graphics.scene_contract import SceneContractError


def _request(canvas: tuple[int, int] = (3840, 2160)) -> CatalogSceneRequest:
    return CatalogSceneRequest(
        entry={
            "kind": "chart-story", "anchor": "own-screen",
            "outStart": 45.0, "outEnd": 45.0 + 24 * 1001 / 30000,
            "spec": {
                "data": "12, 28", "labels": "Before,After", "type": "bars", "emphasize": 1, "unit": "%",
            },
        },
        scene_id="scene-catalog-wash",
        timing={
            "startFrame": 1350, "endFrameExclusive": 1374,
            "fps": {"numerator": "30000", "denominator": "1001"},
            "timelineMapHash": "a" * 64,
        },
        canvas={"width": canvas[0], "height": canvas[1]},
        provenance={"origin": "operator", "requestId": "request-wash"},
    )


def _asset_request() -> CatalogSceneRequest:
    return CatalogSceneRequest(
        entry={
            "kind": "ui-focus-zoom", "anchor": "own-screen",
            "outStart": 0.0, "outEnd": 0.8,
            "spec": {"image": "assets/sample-screen.png", "zoomAt": 0.2},
        },
        scene_id="scene-logo",
        timing={
            "startFrame": 0, "endFrameExclusive": 24,
            "fps": {"numerator": "30", "denominator": "1"},
            "timelineMapHash": "b" * 64,
        },
        canvas={"width": 1920, "height": 1080},
        provenance={"origin": "operator", "requestId": "request-logo"},
    )


class SceneCatalogTests(unittest.TestCase):
    def test_wrapper_uses_fresh_measured_canvas_and_exact_timing(self) -> None:
        scene = wrap_catalog_scene(_request())
        self.assertEqual(scene["composition"]["type"], "catalog")
        self.assertEqual(scene["canvas"], {"width": 3840, "height": 2160})
        self.assertEqual(scene["renderUnits"][0]["unitId"], "catalog-scene")

    def test_aspect_mismatch_fails_before_render(self) -> None:
        with self.assertRaisesRegex(SceneContractError, "aspects"):
            wrap_catalog_scene(_request((1080, 1920)))

    def test_missing_capability_fails_closed(self) -> None:
        request = _request()
        broken = CatalogSceneRequest(
            entry={**request.entry, "kind": "not-registered"},
            scene_id=request.scene_id, timing=request.timing,
            canvas=request.canvas, provenance=request.provenance)
        with self.assertRaisesRegex(
                (SceneContractError, ValueError), "capability|unknown"):
            wrap_catalog_scene(broken)

    def test_renderer_keeps_fractional_rate_and_proves_4k_geometry(self) -> None:
        scene = wrap_catalog_scene(_request())
        result = {
            "path": "/cache/wash.mp4", "cached": False, "key": "k",
            "proof": {"schemaVersion": 1},
        }
        with mock.patch(
                "graphics.scene_catalog.render_entry",
                return_value=result) as render:
            receipt = render_catalog_scene(scene, "/cache")
        entry, cache, rate = render.call_args.args
        self.assertEqual(rate, "30000/1001")
        self.assertAlmostEqual(entry["outEnd"], 24 * 1001 / 30000)
        self.assertEqual(cache, "/cache")
        self.assertEqual(
            receipt["deliveryGeometry"]["placedBBox"], [0, 0, 3840, 2160])

    def test_catalog_assets_bind_selector_and_exact_source_path(self) -> None:
        scene = wrap_catalog_scene(_asset_request())
        contract = catalog_scene_contract(scene)
        self.assertEqual(len(contract["assetBindings"]), 1)
        binding = contract["assetBindings"][0]
        self.assertEqual(binding["field"], "image")
        self.assertEqual(binding["selector"], "assets/sample-screen.png")
        self.assertTrue(binding["sourcePath"].endswith(
            "/templates/motion/assets/sample-screen.png"))
        self.assertEqual(
            binding["sha256"], scene["dependencies"][0]["sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Geometry and pixel fault cases only; no FFmpeg, models, or retained media."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

from audit import audit_safe_zone as safe
from audit.audit_frames import FrameRef
from audit.audit_probe import edge_density, edge_density_image
from captions.caption_plan_pipeline import _destination


def _plan(mode: str = "longform") -> dict:
    """An explicit canonical caption plan never permits legacy geometry fallback."""
    return {"target": {"mode": mode}, "captionsTrack": {"schemaVersion": 1}}


def _stripes(canvas: tuple[int, int], top: int, bottom: int) -> Image.Image:
    """Alternating columns isolate horizontal edges in the requested row range."""
    image = Image.new("L", canvas)
    row = Image.new("L", (canvas[0], 1))
    row.putdata([255 if index % 2 else 0 for index in range(canvas[0])])
    image.paste(row.resize((canvas[0], bottom - top)), (0, top))
    return image


def _old_valid_density(image: Image.Image, top: int, bottom: int) -> float:
    """Historical arithmetic only on already valid, nonempty bands."""
    band = image.convert("L").crop((0, top, image.width, bottom))
    left = band.crop((0, 0, band.width - 1, band.height))
    right = band.crop((1, 0, band.width, band.height))
    values = ImageChops.difference(left, right)
    count = values.point(lambda value: 255 if value > 40 else 0).histogram()[255]
    return count / ((band.width - 1) * band.height)


class SafeZoneGeometryTests(unittest.TestCase):
    """Current destination geometry is reused; malformed/legacy states stay honest."""

    def setUp(self) -> None:
        self.ref = FrameRef("caption1", "caption", 1.0, "/TEST/not-opened.png")

    def test_existing_destination_geometry_is_exact(self) -> None:
        for mode, canvas, top in [("short", (1080, 1920), 1400),
                                  ("longform", (1920, 1080), 980)]:
            actual = safe.resolve_scope(_plan(mode), dict(zip(("width", "height"), canvas)))
            self.assertEqual(actual, safe.SafeZoneScope(canvas, top, canvas[1]))

    def test_malformed_dimensions_reject_before_image_open(self) -> None:
        for value in [True, 0, -1, 1920.0, "1920", float("nan"), None]:
            with patch.object(safe.Image, "open", side_effect=AssertionError("must not open")):
                result = safe.scan_safe_zone([self.ref], _plan(), {"width": value, "height": 1080})
            self.assertEqual(result[0].status, safe.FAIL)

    def test_explicit_caption_canvas_mismatch_fails(self) -> None:
        for canvas in [(1080, 1920), (3840, 2160), (1920, 1079)]:
            result = safe.scan_safe_zone([self.ref], _plan(), dict(zip(("width", "height"), canvas)))
            self.assertEqual(result[0].status, safe.FAIL)

    def test_legacy_passthrough_has_no_implicit_scaling(self) -> None:
        result = safe.scan_safe_zone([self.ref], {"target": {"mode": "longform"}},
                                    {"width": 3840, "height": 2160})
        self.assertEqual(result[0].status, safe.WARN)
        self.assertEqual(result[0].measured, "unmeasured")

    def test_unknown_or_missing_target_cannot_infer_mode(self) -> None:
        for plan in [{}, {"target": {}}, _plan("unknown"), {"target": []}]:
            result = safe.scan_safe_zone([self.ref], plan, {"width": 1920, "height": 1080})
            self.assertEqual(result[0].status, safe.FAIL)

    def test_invalid_destination_insets_fail(self) -> None:
        for bottom in [-1, True, 1080, "100"]:
            destination = _destination(_plan())
            destination["safeZones"]["bottom"] = bottom
            with patch.object(safe, "caption_destination", return_value=destination):
                result = safe.scan_safe_zone([self.ref], _plan(), {"width": 1920, "height": 1080})
            self.assertEqual(result[0].status, safe.FAIL)

    def test_zero_and_single_row_exclusion_are_unqualified(self) -> None:
        for bottom in [0, 1]:
            destination = _destination(_plan())
            destination["safeZones"]["bottom"] = bottom
            with patch.object(safe, "caption_destination", return_value=destination):
                result = safe.scan_safe_zone([self.ref], _plan(), {"width": 1920, "height": 1080})
            self.assertEqual(result[0].status, safe.WARN)
            self.assertEqual(result[0].measured, "unmeasured")

    def test_missing_frames_and_legacy_call_do_not_pass(self) -> None:
        self.assertEqual(safe.scan_safe_zone([])[0].status, safe.FAIL)
        cover = FrameRef("cover", "cover", 0.2, "/TEST/no.png")
        self.assertEqual(safe.scan_safe_zone([cover])[0].status, safe.FAIL)
        self.assertEqual(safe.scan_safe_zone([self.ref])[0].status, safe.WARN)


class SafeZonePixelTests(unittest.TestCase):
    """Actual TEST raster measurement, including the original landscape counterexample."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory(prefix="sniper-safe-zone-TEST-")
        self.addCleanup(self.folder.cleanup)
        self.file = Path(self.folder.name) / "frame.png"

    def scan(self, image: Image.Image, mode: str = "longform") -> object:
        """Run real image loading and measurement for one native destination."""
        image.save(self.file)
        ref = FrameRef("caption1", "caption", 1.0, str(self.file))
        destination = _destination(_plan(mode))
        video = {key: destination[key] for key in ("width", "height")}
        return safe.scan_safe_zone([ref], _plan(mode), video)[0]

    def test_portrait_uniform_zero_is_a_real_measurement(self) -> None:
        result = self.scan(Image.new("L", (1080, 1920)), "short")
        self.assertEqual(result.status, safe.PASS)
        self.assertIn("pixels=561080", result.measured)
        self.assertIn("band=[1400,1920)", result.detail)

    def test_landscape_bottom_detail_warns_instead_of_empty_pass(self) -> None:
        image = _stripes((1920, 1080), 980, 1080)
        result = self.scan(image)
        self.assertEqual(result.status, safe.WARN)
        self.assertIn("band=[980,1080)", result.detail)
        self.assertIsNone(edge_density(str(self.file), 1400, 1920))

    def test_valid_portrait_pixels_retain_original_numeric_result(self) -> None:
        image = _stripes((1080, 1920), 1500, 1700).convert("RGB")
        self.assertEqual(edge_density_image(image, 1400, 1920),
                         _old_valid_density(image, 1400, 1920))
        self.assertEqual(self.scan(image, "short").status, safe.WARN)

    def test_detail_above_landscape_band_is_excluded(self) -> None:
        self.assertEqual(self.scan(_stripes((1920, 1080), 200, 980)).status, safe.PASS)

    def test_half_open_band_and_exact_edge_step(self) -> None:
        image = _stripes((8, 6), 2, 3)
        self.assertEqual(edge_density_image(image, 0, 2), 0.0)
        self.assertEqual(edge_density_image(image, 2, 4), 0.5)
        for value, expected in [(40, 0.0), (41, 1.0)]:
            pair = Image.new("L", (2, 2))
            pair.putdata([0, value, 0, value])
            self.assertEqual(edge_density_image(pair, 0, 2), expected)

    def test_outside_partial_empty_and_invalid_bands_never_measure_zero(self) -> None:
        image = Image.new("L", (8, 6))
        for top, bottom in [(6, 8), (5, 8), (-1, 3), (4, 2), (2, 2), (2, 3), (True, 4)]:
            self.assertIsNone(edge_density_image(image, top, bottom))
        self.assertIsNone(edge_density_image(Image.new("L", (1, 6)), 0, 6))
        self.assertIsNone(edge_density_image(image, 0, 6, -1))

    def test_threshold_equality_is_warning(self) -> None:
        for value, expected in [(0.014999, safe.PASS), (0.015, safe.WARN)]:
            with patch.object(safe, "edge_density_image", return_value=value):
                result = self.scan(Image.new("L", (1920, 1080)))
            self.assertEqual(result.status, expected)

    def test_bad_measurements_fail_without_claiming_visual_defect(self) -> None:
        for value in [None, float("nan"), float("inf"), -0.1, 1.1]:
            with patch.object(safe, "edge_density_image", return_value=value):
                result = self.scan(Image.new("L", (1920, 1080)))
            self.assertEqual(result.status, safe.FAIL)
            self.assertIn("no visual defect inferred", result.detail)

    def test_missing_corrupt_and_wrong_size_images_fail(self) -> None:
        ref = FrameRef("caption1", "caption", 1.0, str(self.file))
        video = {"width": 1920, "height": 1080}
        self.assertEqual(safe.scan_safe_zone([ref], _plan(), video)[0].status, safe.FAIL)
        self.file.write_bytes(b"not an image")
        self.assertEqual(safe.scan_safe_zone([ref], _plan(), video)[0].status, safe.FAIL)
        self.assertEqual(self.scan(Image.new("L", (1080, 1920))).status, safe.FAIL)

    def test_measurement_holds_loaded_pixels_without_reopening_path(self) -> None:
        original = safe.edge_density_image
        def replace_after_load(image: Image.Image, top: int, bottom: int, threshold: int) -> float:
            image.load()
            self.file.write_bytes(b"replacement is not a valid raster")
            return original(image, top, bottom, threshold)
        with patch.object(safe, "edge_density_image", side_effect=replace_after_load):
            with patch.object(safe.Image, "open", wraps=Image.open) as opened:
                result = self.scan(Image.new("L", (1920, 1080)))
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(result.status, safe.PASS)

    def test_result_shape_is_unchanged_but_new_policy_is_explicit(self) -> None:
        result = self.scan(Image.new("L", (1920, 1080)))
        self.assertEqual(set(asdict(result)), {"name", "status", "measured", "detail"})
        self.assertIn(safe.POLICY, result.detail)
        historical = b'{"name":"safe_zone_caption1","status":"pass","measured":"edge density 0.000 in y>1400","detail":"heuristic"}'
        self.assertEqual(json.loads(historical)["status"], "pass")
        self.assertNotIn(safe.POLICY.encode(), historical)


if __name__ == "__main__":
    unittest.main(verbosity=2)

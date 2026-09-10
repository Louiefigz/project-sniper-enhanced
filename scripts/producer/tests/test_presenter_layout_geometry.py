"""Pure declared geometry/expression tests; no media, tools or face observations."""
from __future__ import annotations

import copy
import math
import re
import unittest
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from unittest.mock import patch

from graphics.presenter_layout_contract import PixelRect, PresenterCanvas, PresenterGeometry
from graphics.presenter_layout_geometry import (
    compile_presenter_geometry, presenter_expressions, presenter_frame,
    revalidate_presenter_geometry,
)


def _rect(x: float, y: float, width: float, height: float) -> dict:
    """Build explicitly normalized TEST-only authored geometry."""
    return {"x": x, "y": y, "width": width, "height": height}


def _payload(layout: str = "inset") -> dict:
    """Declare a stationary TEST envelope, not an observed human subject."""
    value = {"schemaVersion": 1, "sourceIds": ["raw-2", "raw-1"], "layout": layout,
             "cropSpace": "held-base-display", "presenterCrop": _rect(.5, 0, .5, 1),
             "protectedPresenterRect": _rect(.65, .2, .2, .5),
             "presenterRect": _rect(.7, .45, .25, .5), "presentationRect": _rect(0, 0, 1, 1),
             "mask": {"kind": "rounded-rect", "radiusPx": 24}, "assetId": "slide-1",
             "assetStart": {"numerator": 1001, "denominator": 30000},
             "presentationFit": "contain", "assetAudio": "discard", "enterFrames": 15,
             "exitFrames": 18, "easing": "smoothstep-v1", "track": False}
    if layout == "bubble":
        value.update(presenterCrop=_rect(.5, .25, .28125, .5),
                     protectedPresenterRect=_rect(.59, .4, .1, .2),
                     presenterRect=_rect(.8, .65, .140625, .25), mask={"kind": "circle"})
    if layout == "split":
        value.update(presenterRect=_rect(.5, 0, .5, 1), presentationRect=_rect(0, 0, .5, 1),
                     mask={"kind": "rect"})
    return value


def _geometry(layout: str = "inset") -> PresenterGeometry:
    """Compile the same 120-frame synthetic full-program declaration."""
    return compile_presenter_geometry(_payload(layout), PresenterCanvas(1920, 1080, 120, "yuv420p"), (3, 120))


def _evaluate(expression: str, variables: dict) -> float:
    """Evaluate generated arithmetic only; this is not FFmpeg qualification."""
    registers = {}
    def store(index: int, value: float) -> float:
        """TEST register evaluation is local to this one pixel expression."""
        registers[index] = value
        return value
    functions = {"clip": lambda x, a, b: min(b, max(a, x)), "min": min, "max": max,
                 "hypot": math.hypot, "abs": abs, "lte": lambda a, b: int(a <= b),
                 "gt": lambda a, b: int(a > b), "lt": lambda a, b: int(a < b),
                 "st": store, "ld": registers.__getitem__}
    for part in expression.split(";"):
        result = eval(part.replace("in-1", "I-1"), {"__builtins__": {}}, functions | variables)
    return result


class PresenterLayoutGeometryTests(unittest.TestCase):
    """Adversarial tests for manual declarations, not executable provenance."""

    def test_all_forms_preserve_endpoints_and_affine_subject_motion(self) -> None:
        """Every written TEST frame preserves isotropic affine subject motion."""
        for layout in ("inset", "bubble", "split"):
            value = _geometry(layout)
            crop, target = value.shape.surfaces.crop, value.shape.surfaces.presenter
            for n in range(120):
                state = presenter_frame(value, n)
                q = max(0, min(1, (n - 3) / 15, (119 - n) / 18))
                p = q * q * (3 - 2 * q)
                self.assertAlmostEqual(state.scale, 1 + p * (value.shape.scale - 1))
                self.assertAlmostEqual(state.viewport.width, 1920 + p * (target.width - 1920))
                self.assertGreaterEqual(state.visible_crop().x, -1e-7)
                self.assertLessEqual(state.visible_crop().x + state.visible_crop().width, 1920 + 1e-7)
            self.assertEqual(presenter_frame(value, 3).viewport, PixelRect(0, 0, 1920, 1080))
            self.assertEqual(presenter_frame(value, 119).translation, (0, 0))
            self.assertEqual(presenter_frame(value, 18).viewport, target)
            self.assertEqual(presenter_frame(value, 101).visible_crop(), crop)

    def test_each_protected_corner_stays_inside_every_written_rounded_mask(self) -> None:
        """Exhaustively supplement the convex endpoint proof for all TEST forms."""
        for layout in ("inset", "bubble", "split"):
            value = _geometry(layout)
            for n in range(120):
                self._assert_corners(value, n)

    def _assert_corners(self, value: PresenterGeometry, frame: int) -> None:
        """Check an independently expressed distance for each affine corner."""
        state = presenter_frame(value, frame)
        box, radius = state.viewport, state.radius_px
        for x, y in value.shape.surfaces.protected.corners():
            x, y = state.scale * x + state.translation[0], state.scale * y + state.translation[1]
            dx = max(box.x + radius - x, 0, x - (box.x + box.width - radius))
            dy = max(box.y + radius - y, 0, y - (box.y + box.height - radius))
            self.assertLessEqual(math.hypot(dx, dy), radius + 1e-7)

    def test_expressions_use_original_clock_after_exact_branch_trim(self) -> None:
        """Global and trimmed filter counters produce the same sampled corners."""
        value = _geometry()
        full, trimmed = presenter_expressions(value), presenter_expressions(value, 3)
        for frame in (3, 4, 10, 18, 60, 101, 118, 119):
            a = re.findall(r"[xy][0-3]='([^']+)'", full.perspective)
            b = re.findall(r"[xy][0-3]='([^']+)'", trimmed.perspective)
            left = [_evaluate(expr, {"I": frame + 1}) for expr in a]
            right = [_evaluate(expr, {"I": frame - 3 + 1}) for expr in b]
            self.assertEqual(left, right)
            state = presenter_frame(value, frame)
            self.assertAlmostEqual(left[0], state.translation[0] + (state.scale - 1) / 2)
            self.assertAlmostEqual(left[2] - left[0], 1920 * state.scale)
            self.assertAlmostEqual(left[0] + .5, state.translation[0] + .5 * state.scale)
        self.assertEqual(trimmed.gate, "gt(n,3)*lt(n,119)")
        self.assertIn("N+3", trimmed.alpha)
        self.assertFalse(any(token in trimmed.perspective for token in ("/TB", "PTS", "setpts")))

    def test_bubble_is_a_real_circle_not_a_rectangular_surrogate(self) -> None:
        """Final binary mask excludes square corners and includes its centre."""
        value = _geometry("bubble")
        expression = presenter_expressions(value).alpha.split("'", 2)[1]
        box = value.shape.surfaces.presenter
        self.assertEqual(_evaluate(expression, {"N": 18, "X": box.x, "Y": box.y}), 0)
        self.assertEqual(_evaluate(expression, {"N": 18, "X": box.x + box.width / 2 - .5,
                                                "Y": box.y + box.height / 2 - .5}), 255)
        self.assertEqual(_evaluate(expression, {"N": 3, "X": 0, "Y": 0}), 255)
        self.assertEqual(_evaluate(expression, {"N": 119, "X": 1919, "Y": 1079}), 255)

    def test_source_order_offset_and_unqualified_scope_are_preserved(self) -> None:
        """Pure compilation supplies no observation, executable or approval fact."""
        value = _geometry()
        self.assertEqual(value.declaration.source_ids, ("raw-2", "raw-1"))
        self.assertEqual(value.declaration.asset_start, Fraction(1001, 30000))
        self.assertFalse(value.executable or value.installed_mapping_qualified or value.framing_observed)
        self.assertFalse(presenter_expressions(value).installed_mapping_qualified)
        with self.assertRaises(FrozenInstanceError):
            value.shape.scale = 2

    def test_closed_payload_rejects_unknown_policy_or_missing_fields(self) -> None:
        """No controls, asset audio, unknown mask or inferred policy is accepted."""
        faults = [("extra", 1), ("track", True), ("schemaVersion", True), ("assetAudio", "keep"),
                  ("cropSpace", "raw-source"), ("easing", "linear"), ("layout", "auto"),
                  ("mask", {"kind": "circle"}), ("sourceIds", ["same", "same"]),
                  ("assetStart", {"numerator": 2, "denominator": 4})]
        for key, item in faults:
            value = _payload(); value[key] = item
            self._reject(value)
        value = _payload(); del value["assetAudio"]
        self._reject(value)

    def _reject(self, payload: dict) -> None:
        """Assert a declaration fails before any expression is returned."""
        with self.assertRaises(ValueError):
            compile_presenter_geometry(payload, PresenterCanvas(1920, 1080, 120, "yuv420p"), (3, 120))

    def test_noncanonical_and_unbounded_numbers_fail(self) -> None:
        """Reject boolean, nonfinite, enormous, string and negative-zero bounds."""
        for item in (True, float("nan"), float("inf"), 10 ** 400, "0.2", -0.0):
            value = _payload(); value["presenterCrop"]["x"] = item
            self._reject(value)

    def test_unsupported_depth_canvas_and_upscale_fail(self) -> None:
        """Do not turn a format string into a hidden precision reduction."""
        for pixel_format in ("yuv420p10le", "gbrp16le", "rgba", "unknown", None):
            with self.assertRaisesRegex(ValueError, "8-bit"):
                PresenterCanvas(1920, 1080, 120, pixel_format)
        for dimensions in ((1921, 1080), (8192, 4320), (4096, 4096)):
            with self.assertRaises(ValueError):
                PresenterCanvas(*dimensions, 120, "yuv420p")
        value = _payload(); value["presenterRect"] = _rect(0, 0, .6, 1)
        self._reject(value)

    def test_bad_crop_mask_aspect_and_split_cells_fail(self) -> None:
        """Reject masked subject corners, stretch, gaps and off-canvas intent."""
        faults = [_payload(), _payload("bubble"), _payload(), _payload("split"), _payload()]
        faults[0]["protectedPresenterRect"] = _rect(.49, .2, .1, .2)
        faults[1]["protectedPresenterRect"] = copy.deepcopy(faults[1]["presenterCrop"])
        faults[2]["presenterRect"]["height"] = .4
        faults[3]["presentationRect"]["width"] -= 1e-12
        faults[4]["presenterCrop"]["x"] = .6
        for value in faults:
            self._reject(value)

    def test_ramps_require_real_last_written_endpoint(self) -> None:
        """No overlapping ramps, zero duration or unreachable return frame."""
        canvas = PresenterCanvas(1920, 1080, 120, "yuv420p")
        for span in ((3, 36), (120, 120), (3, 121), (True, 120), [3, 120]):
            with self.assertRaises(ValueError):
                compile_presenter_geometry(_payload(), canvas, span)
        for key in ("enterFrames", "exitFrames"):
            value = _payload(); value[key] = 0
            self._reject(value)
        value = compile_presenter_geometry(_payload(), canvas, (3, 37))
        self.assertEqual(presenter_frame(value, 18).viewport, value.shape.surfaces.presenter)

    def test_replaced_dataclasses_are_not_validation_authority(self) -> None:
        """Expression compilation repeats checks on all replaced internal state."""
        value = _geometry()
        bad_shape = replace(value.shape, scale=value.shape.scale + .1)
        bad_surface = replace(value.shape.surfaces, protected=PixelRect(0, 0, 1920, 1080))
        bad_timing = replace(value.timing, end_frame_exclusive=20)
        faults = [replace(value, shape=bad_shape), replace(value, timing=bad_timing),
                  replace(value, shape=replace(value.shape, surfaces=bad_surface)),
                  replace(value, declaration=replace(value.declaration, source_ids=("a", "a")))]
        for fault in faults:
            with self.assertRaises(ValueError):
                presenter_expressions(fault)
        revalidate_presenter_geometry(value)

    def test_unknown_frame_origins_and_indices_fail(self) -> None:
        """Only whole-base and exact-operation origins can compile this branch."""
        value = _geometry()
        for origin in (1, 4, True, -1, 120):
            with self.assertRaises(ValueError):
                presenter_expressions(value, origin)
        for frame in (-1, 120, True, 1.5):
            with self.assertRaises(ValueError):
                presenter_frame(value, frame)

    def test_portrait_vertical_split_and_pixel_square_bubble(self) -> None:
        """Geometry is display-pixel based, not a landscape-only mask shortcut."""
        value = _payload("split")
        value.update(presenterCrop=_rect(0, .5, 1, .5), protectedPresenterRect=_rect(.3, .6, .4, .2),
                     presenterRect=_rect(0, .5, 1, .5), presentationRect=_rect(0, 0, 1, .5))
        geometry = compile_presenter_geometry(value, PresenterCanvas(1080, 1920, 120, "gbrp"), (3, 120))
        self.assertEqual(presenter_frame(geometry, 18).viewport, PixelRect(0, 960, 1080, 960))
        revalidate_presenter_geometry(geometry)
        value = _payload("bubble"); value["presenterRect"] = _rect(.5, .5, .25, .25)
        self._reject(value)  # Equal normalized sides are not a circle on a 16:9 canvas.

    def test_input_stays_immutable_and_identifiers_never_become_expressions(self) -> None:
        """Untrusted provenance names are retained as data, not filter language."""
        value = _payload(); value["assetId"] = "asset';movie=/unexpected"
        before = copy.deepcopy(value)
        geometry = compile_presenter_geometry(value, PresenterCanvas(1920, 1080, 120, "yuv420p"), (3, 120))
        expression = presenter_expressions(geometry)
        self.assertEqual(value, before)
        self.assertNotIn("unexpected", expression.perspective + expression.alpha)

    def test_large_frame_count_keeps_pure_validation_work_bounded(self) -> None:
        """Continuous proof does not require a new unbounded whole-video loop."""
        import graphics.presenter_layout_geometry as module
        with patch.object(module, "_verify_frame", wraps=module._verify_frame) as verify:
            compile_presenter_geometry(_payload(), PresenterCanvas(1920, 1080, 432000, "yuv420p"), (3, 432000))
        self.assertLessEqual(verify.call_count, 29)

    def test_revalidation_preserves_original_normalized_decimal_not_reverse_rounding(self) -> None:
        """A legitimate edge-aligned crop must survive its pixel projection intact."""
        payload = _payload()
        payload["presenterCrop"] = _rect(.085, 0, .915, 1)
        payload["presenterRect"] = _rect(.4, .4, .4575, .5)
        payload["protectedPresenterRect"] = _rect(.5, .3, .1, .2)
        value = compile_presenter_geometry(payload, PresenterCanvas(1920, 1080, 120, "yuv420p"), (3, 120))
        revalidate_presenter_geometry(value)
        self.assertEqual(value.shape.declaration_rectangles[0], (.085, 0, .915, 1))
        crop = replace(value.shape.surfaces.crop, x=value.shape.surfaces.crop.x + 1e-9)
        changed = replace(value, shape=replace(value.shape, surfaces=replace(value.shape.surfaces, crop=crop)))
        with self.assertRaisesRegex(ValueError, "pixel surfaces differ"):
            presenter_expressions(changed)

    def test_split_topology_uses_exact_declared_cells_not_pixel_float_sums(self) -> None:
        """Valid normalized splits survive; actual subpixel gaps still reject."""
        for width, height, fraction in ((1920, 1080, .052), (1080, 1920, .051), (3840, 2160, .052)):
            value = _payload("split")
            value.update(presenterCrop=_rect(0, 0, fraction, 1),
                         presenterRect=_rect(0, 0, fraction, 1),
                         presentationRect=_rect(fraction, 0, 1 - fraction, 1),
                         protectedPresenterRect=_rect(fraction / 4, .3, fraction / 2, .4))
            canvas = PresenterCanvas(width, height, 120, "yuv420p")
            geometry = compile_presenter_geometry(value, canvas, (3, 120))
            revalidate_presenter_geometry(geometry)
            self.assertFalse(geometry.executable)  # Not even-pixel/raster admission.
            value["presentationRect"]["width"] -= 1e-12
            with self.assertRaisesRegex(ValueError, "tile"):
                compile_presenter_geometry(value, canvas, (3, 120))


if __name__ == "__main__":
    unittest.main(verbosity=2)

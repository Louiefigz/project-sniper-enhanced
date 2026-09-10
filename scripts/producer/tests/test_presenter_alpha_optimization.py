"""Exact TEST reference for the formerly expanded, expensive presenter mask.

This frozen arithmetic reference is deliberately not used by production. Pure
evaluation is not raster/visual qualification; native comparisons live beside
the existing shared-compositor tests and in the retained1080p experiment.
"""
from __future__ import annotations

import unittest

from graphics.presenter_layout_contract import PresenterGeometry
from graphics.presenter_layout_geometry import presenter_expressions
from test_presenter_layout_geometry import _evaluate, _geometry


def legacy_alpha(value: PresenterGeometry, progress: str) -> str:
    """Retain original operation order and17-digit numeric expansion exactly."""
    def lerp(initial: float, final: float) -> str:
        """Frozen reference interpolation, independent of production helpers."""
        return f"({format(initial, '.17g')}+({format(final - initial, '.17g')})*({progress}))"

    target = value.shape.surfaces.presenter
    x, y = lerp(0, target.x), lerp(0, target.y)
    width = lerp(value.canvas.width, target.width)
    height = lerp(value.canvas.height, target.height)
    radius = lerp(0, value.shape.radius_px)
    dx = f"(abs(X+0.5-({x})-({width})/2)-(({width})/2-({radius})))"
    dy = f"(abs(Y+0.5-({y})-({height})/2)-(({height})/2-({radius})))"
    distance = f"(hypot(max({dx},0),max({dy},0))+min(max({dx},{dy}),0)-({radius}))"
    return f"geq=lum_expr='255*lte({distance},0)'"


def reference_expression(value: PresenterGeometry, origin: int) -> str:
    """Reproduce original global-frame smoothstep independently, without a cache."""
    timing = value.timing
    counter = f"N+{origin}"
    q = (f"clip(min((({counter})-{timing.start_frame})/{timing.enter_frames},"
         f"({timing.end_frame_exclusive - 1}-({counter}))/{timing.exit_frames}),0,1)")
    return legacy_alpha(value, f"(({q})*({q})*(3-2*({q})))").split("'", 2)[1]


class PresenterAlphaOptimizationTests(unittest.TestCase):
    """Arithmetic parity does not replace the actual all-frame native comparisons."""

    def test_progress_is_evaluated_once_without_previous_pixel_state(self) -> None:
        """All local registers are initialized before any mask result is read."""
        expression = presenter_expressions(_geometry(), 3).alpha.split("'", 2)[1]
        self.assertEqual(expression.count("clip("), 3)  # One cubic progress value.
        self.assertTrue(expression.startswith("st(0,"))
        self.assertEqual(expression.count("st("), 4)
        self.assertNotIn("if(", expression)  # No cross-pixel/frame lazy state.

    def test_original_arithmetic_matches_at_all_ramp_phases_and_mask_edges(self) -> None:
        """Compare fresh independent local state including reversed pixel traversal."""
        for kind in ("inset", "bubble", "split"):
            self._assert_form(kind)

    def _assert_form(self, kind: str) -> None:
        """Keep original and exact-trimmed clocks at each boundary and hold phase."""
        value = _geometry(kind)
        box = value.shape.surfaces.presenter
        points = ((0, 0), (1919, 1079), (box.x, box.y),
                  (box.x + box.width / 2 - .5, box.y + box.height / 2 - .5),
                  (box.x + box.width - .5, box.y + box.height - .5))
        for origin in (0, 3):
            actual = presenter_expressions(value, origin).alpha.split("'", 2)[1]
            reference = reference_expression(value, origin)
            samples = [(frame, x, y) for frame in (3, 4, 10, 18, 60, 101, 118, 119)
                       for x, y in reversed(points)]
            self._assert_samples((actual, reference), samples, origin)

    def _assert_samples(self, expressions: tuple, samples: list, origin: int) -> None:
        """Require exact0/255 equality, never an image-error tolerance."""
        actual, reference = expressions
        for frame, x, y in samples:
            variables = {"N": frame - origin, "X": x, "Y": y}
            self.assertEqual(_evaluate(actual, variables), _evaluate(reference, variables))


if __name__ == "__main__":
    unittest.main()

"""Independent equations and strict gamut policy; no media/approval fixtures."""
from __future__ import annotations

import math
import unittest

from color.source_picture_transform_reference import (
    finite_sample, limited_ycbcr_to_linear, limited_ycbcr_to_rgb, linear_to_bt709,
    reference_bt709_rgb, require_unit_gamut, xvycc709_to_linear,
)


class SourcePictureReferenceTests(unittest.TestCase):
    """Keep valid identity, signed extension and rejection distinct."""

    def test_legal_neutral_ramp_is_display_identity_not_mandatory_pixel_change(self) -> None:
        """Legal xvYCC RGB follows the same 2.4 display curve as this 709 path."""
        for code in (16, 17, 32, 64, 100, 128, 180, 234, 235):
            expected = (code - 16) / 219
            for actual in reference_bt709_rgb((code, 128, 128)):
                self.assertAlmostEqual(actual, expected, places=13)
            self.assertAlmostEqual(xvycc709_to_linear(expected), expected ** 2.4, places=14)

    def test_extended_values_use_signed_rec709_inverse_not_display_power(self) -> None:
        """Ground independent constants in zimg3.0.6, not FFmpeg output."""
        self.assertAlmostEqual(xvycc709_to_linear(-0.01), -0.01 / 4.5, places=14)
        expected = ((1.1 + 1.09929682680944 - 1) / 1.09929682680944) ** (1 / 0.45)
        self.assertAlmostEqual(xvycc709_to_linear(1.1), expected, places=14)
        self.assertAlmostEqual(xvycc709_to_linear(-1.1), -expected, places=14)
        self.assertNotAlmostEqual(expected, 1.1 ** 2.4, places=5)

    def test_white_black_chroma_and_extended_codes_are_not_preclamped(self) -> None:
        """The matrix is evaluated before deciding whether target gamut fits."""
        self.assertEqual(limited_ycbcr_to_rgb((16, 128, 128)), (0, 0, 0))
        self.assertEqual(limited_ycbcr_to_rgb((235, 128, 128)), (1, 1, 1))
        self.assertLess(min(limited_ycbcr_to_linear((0, 128, 128))), 0)
        self.assertGreater(max(limited_ycbcr_to_linear((255, 128, 128))), 1)
        self.assertLess(min(limited_ycbcr_to_linear((100, 16, 240))), 0)
        for values in ((0, 128, 128), (255, 128, 128), (100, 16, 240)):
            with self.assertRaisesRegex(ValueError, "outside"):
                reference_bt709_rgb(values)

    def test_no_gamut_epsilon_or_nonfinite_escape(self) -> None:
        """Even a representable one-ULP excursion is not silently forgiven."""
        for sample in (-1e-45, math.nextafter(1, math.inf), math.nan, math.inf, -math.inf):
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                require_unit_gamut((0, sample, 1))
            with self.assertRaises(ValueError):
                linear_to_bt709(sample)
        self.assertEqual(require_unit_gamut((0, 0.5, 1)), (0, 0.5, 1))

    def test_malformed_overflow_unbounded_iterables_and_wrong_channels_reject(self) -> None:
        """No fallback, implicit numeric casts or unbounded iterator collection."""
        for value in (True, "0.1", None, 10 ** 500, math.inf, math.nan):
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError):
                finite_sample(value)
        with self.assertRaises(ValueError):
            xvycc709_to_linear(1e308)
        for samples in ((), (0, 1), (0, 1, 0, 1), iter((0, 1, 0))):
            with self.assertRaises(ValueError):
                require_unit_gamut(samples)
        with self.assertRaises(ValueError):
            limited_ycbcr_to_rgb((256, 0, 0))

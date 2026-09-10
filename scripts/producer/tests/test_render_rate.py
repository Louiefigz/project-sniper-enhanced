"""Exact FPS tokens prevent ambiguous HyperFrames decimal rates."""
from __future__ import annotations

import unittest
from fractions import Fraction

from graphics.hyperframes_invocation import RenderInvocation, _command
from graphics.render_rate import normalize_render_rate


class RenderRateTests(unittest.TestCase):
    def test_released_fractional_rates_keep_exact_cli_tokens(self) -> None:
        cases = (
            ({"numerator": "24000", "denominator": "1001"}, "24000/1001"),
            (Fraction(30000, 1001), "30000/1001"),
            (60000 / 1001, "60000/1001"),
            (30, "30"),
        )
        for raw, token in cases:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_render_rate(raw).token, token)

    def test_ambiguous_decimal_and_unreduced_rate_fail_closed(self) -> None:
        for value in (
                29.97, "60000/2002",
                {"numerator": "60", "denominator": "2"},
                "030/1", 0, True):
            with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError, "render FPS"):
                normalize_render_rate(value)

    def test_hyperframes_command_uses_rational_not_decimal(self) -> None:
        request = RenderInvocation(
            "/runtime", "compositions/card.html", "mov", {},
            "/output.mov", 30000 / 1001)
        command = _command(request, "/runtime/cli.js", {
            "node": "/runtime/node", "browser": "/runtime/browser",
            "ffmpeg": "/runtime/ffmpeg", "ffprobe": "/runtime/ffprobe",
        })
        self.assertEqual(command[command.index("--fps") + 1], "30000/1001")
        self.assertNotIn("29.97002997", command)


if __name__ == "__main__":
    unittest.main(verbosity=2)

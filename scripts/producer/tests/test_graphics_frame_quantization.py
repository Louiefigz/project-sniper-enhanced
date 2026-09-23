"""Exact HyperFrames frame quantization at transcript word-edge timings."""
from __future__ import annotations

import math
import re
import tempfile
import unittest
from unittest import mock

from graphics import graphics_render as render
from graphics.composition_transform import set_root_duration
from graphics.frame_quantization import (
    hyperframes_duration,
    placement_frame_span,
    rounded_frame_index,
)


def _catalog_entry(start: float, end: float) -> dict:
    return {
        "kind": "line-swap", "anchor": "free-band",
        "outStart": start, "outEnd": end,
        "spec": {
            "lineA": "First action", "lineB": "Better result",
            "underlineWord": "result",
        },
    }


class FrameQuantizationTests(unittest.TestCase):
    def _work(self, entry: dict, fps: float = 30.0):
        captured = []

        def materialize(work, _cache, _ext):
            captured.append(work)
            return {"proof": {"schemaVersion": 1}}

        with tempfile.TemporaryDirectory() as cache, \
                mock.patch.object(render, "content_hash", return_value="a" * 40), \
                mock.patch.object(render, "_materialize_work",
                                  side_effect=materialize):
            render.render_entry_at_rate(entry, cache, fps)
        return captured[0]

    def test_real_word_edges_shorten_to_placement_span(self) -> None:
        entry = _catalog_entry(7.16, 9.10)
        work = self._work(entry)
        self.assertEqual(placement_frame_span(7.16, 9.10, 30.0), 58)
        self.assertLess(work.duration, 9.10 - 7.16)
        self.assertEqual(math.ceil(work.duration * 30.0), 58)
        self.assertEqual(rounded_frame_index(work.duration, 30.0), 58)
        self.assertEqual(entry["outEnd"], 9.10)
        self.assertTrue(render._terminal_clear_required(work))

    def test_word_edges_extend_to_placement_span(self) -> None:
        entry = _catalog_entry(7.16, 9.084)
        work = self._work(entry)
        self.assertEqual(placement_frame_span(7.16, 9.084, 30.0), 58)
        self.assertGreater(work.duration, 9.084 - 7.16)
        self.assertEqual(math.ceil(work.duration * 30.0), 58)

    def test_timeline_quantization_is_bidirectional_and_idempotent(self) -> None:
        windows = ((7.16, 9.10, 30.0), (7.16, 9.084, 30.0),
                   (0.1, 0.3604, 25.0))
        for start, end, fps in windows:
            with self.subTest(start=start, end=end, fps=fps):
                expected = placement_frame_span(start, end, fps)
                first = render.timeline_padded_entry(
                    _catalog_entry(start, end), fps)
                second = render.timeline_padded_entry(first, fps)
                self.assertEqual(first, second)
                self.assertAlmostEqual(first["outEnd"] - first["outStart"],
                                       expected / fps)

    def test_duration_serialization_preserves_exact_ceil_frame_count(self) -> None:
        duration = hyperframes_duration(58, 30.0)
        html = '<div data-composition-id="x" data-duration="3"></div>'
        transformed = set_root_duration(html, duration)
        encoded = float(re.search(
            r'data-duration="([^"]+)"', transformed).group(1))
        self.assertEqual(math.ceil(encoded * 30.0), 58)

    def test_retired_statement_sequence_fails_before_rendering(self) -> None:
        entry = {
            "kind": "statement-card", "anchor": "free-band",
            "outStart": 7.16, "outEnd": 9.70,
            "spec": {
                "variant": "module", "statements": "FIRST|SECOND",
                "statementLands": 2.24, "bg": "dark", "accent": "#D7FF3F",
            },
        }
        with tempfile.TemporaryDirectory() as cache, self.assertRaisesRegex(
                ValueError, "retired"):
            render.render_entry_at_rate(entry, cache, 30.0)

    def test_subframe_window_fails_before_hyperframes(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one timeline frame"):
            render.timeline_padded_entry(_catalog_entry(1.001, 1.002), 30.0)

    def test_retired_module_array_cannot_reach_renderer(self) -> None:
        entry = {"kind": "module-pipeline", "anchor": "own-screen",
                 "outStart": 0, "outEnd": 4,
                 "spec": {"headlineLines": "First", "footChip": "Second",
                          "moduleLands": [0, 2], "exit": "hold"}}
        with self.assertRaisesRegex(ValueError, "retired"):
            self._work(entry)


if __name__ == "__main__":
    unittest.main(verbosity=2)

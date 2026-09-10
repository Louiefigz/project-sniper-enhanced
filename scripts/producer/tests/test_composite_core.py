"""Bounded-pass compositor contract regressions."""
from __future__ import annotations

import unittest

from graphics.composite_core import CompositeOptions, composite


def _clips(count: int) -> list[dict]:
    return [
        {
            "path": f"/overlay-{index:02d}.mov",
            "outStart": float(count - index),
            "outEnd": float(count - index) + 0.5,
        }
        for index in range(count)
    ]


class CompositeCoreTests(unittest.TestCase):
    def test_twenty_four_overlays_build_one_ordered_encode(self) -> None:
        commands: list[list[str]] = []
        result = composite(
            "/base.mp4", _clips(24), "/output.mp4",
            CompositeOptions(
                eof_pass=True, ydif_file="/ydif.log",
                command_runner=commands.append),
        )
        self.assertEqual(result, 1)
        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command.count("-i"), 25)
        graph = command[command.index("-filter_complex") + 1]
        self.assertEqual(graph.count("setpts=PTS-STARTPTS+"), 24)
        self.assertEqual(graph.count("]overlay="), 24)
        self.assertIn("[24:v]setpts=PTS-STARTPTS+24.0000/TB[ov23]", graph)
        self.assertIn("[1:v]setpts=PTS-STARTPTS+1.0000/TB[ov0]", graph)
        self.assertEqual(command.count("/ydif.log"), 0)
        self.assertIn("file='/ydif.log'", graph)

    def test_empty_overlay_set_fails_before_command(self) -> None:
        commands: list[list[str]] = []
        with self.assertRaisesRegex(RuntimeError, "at least one overlay"):
            composite(
                "/base.mp4", [], "/output.mp4",
                CompositeOptions(command_runner=commands.append),
            )
        self.assertEqual(commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

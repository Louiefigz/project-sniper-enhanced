"""Pure ordered-caption graph tests; no media or execution authority is minted."""
from __future__ import annotations

import unittest
from dataclasses import replace

from _common import pl  # noqa: F401
from graphics.composite_core import CompositeOptions, caption_layer_policy, composite, ordered_clips, validate_caption_tails
from guided_caption_layers import caption_page_bound
from opening_prefix_contract import PrefixClock


def page(start: int = 0, end: int = 900) -> dict:
    """Explicit synthetic full-native page; no corresponding media is claimed."""
    return {"path": "/TEST-page.mov", "outStart": start / 30, "outEnd": end / 30,
        "anchor": "own-screen", "x": 0, "y": 0, "startFrame": start, "endFrameExclusive": end,
        "compositionRole": "caption-page", "captionPageId": "a" * 64}


def graphic(start: int) -> dict:
    """An ordinary graphic that would sort after the earlier caption page."""
    return {"path": f"/TEST-graphic-{start}.mov", "outStart": start / 30, "outEnd": 29,
            "startFrame": start, "endFrameExclusive": 870, "anchor": "own-screen"}


class CaptionLayerTests(unittest.TestCase):
    """Retain old None behavior and reject fake/ambiguous ordered tails."""

    def test_tail_above_later_graphics_and_original_origin_before_trim(self) -> None:
        """Layer order is not global outStart order when held captions are explicit."""
        clips = [graphic(150), graphic(30), page()]
        commands = []
        options = CompositeOptions(command_runner=commands.append, frame_rate="30",
            frame_range=(3, 10), video_only=True, eof_pass=True, caption_tail=1)
        composite("/TEST-base.mp4", clips, "/TEST-output.mp4", options)
        cmd = commands[0]
        inputs = [cmd[index + 1] for index, value in enumerate(cmd) if value == "-i"]
        self.assertEqual(inputs, ["/TEST-base.mp4", graphic(30)["path"], graphic(150)["path"], page()["path"]])
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("[3:v]setpts=PTS-STARTPTS+0*1/(30*TB)[ov2]", graph)
        self.assertIn("[gc1][ov2]overlay", graph)
        self.assertTrue(graph.endswith("trim=start_frame=3:end_frame=10,setpts=PTS-STARTPTS[range]"))

    def test_none_legacy_command_and_metadata_unchanged(self) -> None:
        """Omitted/default None produces exactly the same ordinary command."""
        commands = []
        options = CompositeOptions(command_runner=commands.append)
        composite("base", [graphic(100), graphic(0)], "out", options)
        composite("base", [graphic(100), graphic(0)], "out", replace(options, caption_tail=None))
        self.assertEqual(commands[0], commands[1])
        self.assertEqual(caption_layer_policy(None), {})
        with self.assertRaisesRegex(ValueError, "explicit"):
            ordered_clips([page()])

    def test_malformed_or_unqualified_page_tails_reject(self) -> None:
        """Page layout, ordering, count and declared identity remain closed."""
        for tail in (True, -1, 2):
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                ordered_clips([page()], tail)
        for row in ({**page(), "scaleDims": [10, 20]}, {**page(), "x": 1},
                    {**page(), "captionPageId": "x" * 64}, {**page(), "startFrame": False}):
            with self.assertRaises(ValueError):
                ordered_clips([row], 1)
        for rows in ([page(900, 1800), page()], [page(), page(899, 1800)]):
            with self.assertRaises(ValueError):
                ordered_clips(rows, 2)
        with self.assertRaises(ValueError):
            validate_caption_tails(((), ()), (0, 0))
        validate_caption_tails(((page(),), ()), (1, 0))

    def test_whole_body_page_bound_counts_later_pages_before_render(self) -> None:
        """Full plan plus page upper bound cannot exceed the unchanged native cap."""
        clock = PrefixClock("30000/1001", 689 * 899, 1920, 1080)
        with self.assertRaisesRegex(RuntimeError, "workload"):
            caption_page_bound(clock, (8, 2), 120)
        clock = replace(clock, total_frames=23 * 899)
        accepted = caption_page_bound(clock, (8, 2), 120)
        self.assertEqual(accepted["fullPageBound"], 23)
        self.assertEqual(accepted["openingPageBound"], 1)
        with self.assertRaisesRegex(RuntimeError, "workload"):
            caption_page_bound(replace(clock, total_frames=24 * 899), (8, 2), 120)


if __name__ == "__main__":
    unittest.main()

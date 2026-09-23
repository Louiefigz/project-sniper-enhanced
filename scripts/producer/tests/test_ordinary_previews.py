"""Ordinary preview dependency, coverage, phase and admission regressions."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from graphics.composite_core import CompositeOptions, composite
from ordinary_preview_windows import preparation_key, preview_windows, window_key
from ordinary_previews import _current
from studio.owned_inspection import require_worker


def request() -> dict:
    """Return a synthetic ten-graphic five-minute plan; no media approval."""
    track = [{"kind": "line-swap", "outStart": index * 30 + 5, "outEnd": index * 30 + 8,
              "spec": {"text": f"TEST {index}"}} for index in range(10)]
    return {"plan": {"graphicsTrack": track, "planVersion": 1, "audioGain": 0},
            "manifest": {"sources": [{"path": "/TEST/source.mp4"}]}, "pins": {"/TEST/code.py": "code"},
            "packet": {"authority": {"planHash": "old", "pipelineDigest": "code"}, "dependenciesHash": "sources",
                       "units": [{"id": "plan", "hash": "plan"}]
                       + [{"id": f"graphicsTrack/{i}", "hash": f"graphic-{i}"} for i in range(10)]}}


class OrdinaryPreviewTests(unittest.TestCase):
    """Prove local reuse does not erase broader changes or restart animations."""

    def test_copy_edits_reuse_base_but_change_only_intersecting_clips(self) -> None:
        before = request()
        after = deepcopy(before)
        for index in (2, 5, 8):
            after["plan"]["graphicsTrack"][index]["spec"]["text"] = "TEST changed"
        after["packet"]["authority"]["planHash"] = "new"
        self.assertEqual(preparation_key(before), preparation_key(after))
        prepared = {"key": preparation_key(before), "frameRate": "30"}
        windows = preview_windows(before["plan"], before["packet"], ("30", 9000))
        changed = [window for window in windows
                   if window_key(window, before, prepared) != window_key(window, after, prepared)]
        self.assertEqual(len(changed), 3)
        self.assertEqual(len(windows) - len(changed), 10)

    def test_global_and_asset_changes_invalidate_preparation(self) -> None:
        original = request()
        for field, value in (("audioGain", 2), ("cutTrack", []), ("captions", {"burn": True})):
            changed = deepcopy(original)
            changed["plan"][field] = value
            self.assertNotEqual(preparation_key(original), preparation_key(changed))
        changed = deepcopy(original)
        changed["packet"]["dependenciesHash"] = "changed media/font/catalog"
        self.assertNotEqual(preparation_key(original), preparation_key(changed))

    def test_timing_kind_and_unknown_entry_fields_invalidate_base(self) -> None:
        original = request()
        for field, value in (("outStart", 7), ("kind", "count-up"), ("unknown", True)):
            changed = deepcopy(original)
            changed["plan"]["graphicsTrack"][0][field] = value
            self.assertNotEqual(preparation_key(original), preparation_key(changed))

    def test_long_graphic_is_fully_covered_with_bounded_overlapping_windows(self) -> None:
        value = request()
        value["plan"]["graphicsTrack"] = [{"outStart": 10, "outEnd": 50}]
        windows = preview_windows(value["plan"], value["packet"], ("30000/1001", 9000))
        graphic = [row for row in windows if "graphicsTrack/0" in row["units"]]
        self.assertLessEqual(graphic[0]["startFrame"], 240)
        self.assertGreaterEqual(graphic[-1]["endFrameExclusive"], 1550)
        self.assertTrue(all(row["endFrameExclusive"] - row["startFrame"] <= 359 for row in graphic))
        self.assertTrue(all(left["endFrameExclusive"] > right["startFrame"] for left, right in zip(graphic, graphic[1:])))

    def test_no_graphics_still_has_plan_context(self) -> None:
        value = request()
        value["plan"]["graphicsTrack"] = []
        windows = preview_windows(value["plan"], value["packet"], ("30", 120))
        self.assertEqual(len(windows), 3)
        self.assertTrue(all("plan" in row["units"] for row in windows))

    def test_ordinary_range_preserves_seconds_gate_and_global_animation_origin(self) -> None:
        commands = []
        clip = {"path": "overlay.mov", "outStart": 5.1, "outEnd": 8.2, "x": 0, "y": 0}
        composite("base.mp4", [clip], "window.mp4", CompositeOptions(eof_pass=True,
            frame_rate="30", frame_range=(180, 240), video_only=True, ordinary_timing=True,
            command_runner=commands.append))
        graph = commands[0][commands[0].index("-filter_complex") + 1]
        self.assertIn("PTS-STARTPTS+5.1000/TB", graph)
        self.assertIn("between(t,5.1000,8.2000)", graph)
        self.assertLess(graph.index("overlay="), graph.index("trim=start_frame=180:end_frame=240"))
        self.assertIn("-an", commands[0])

    def test_stale_admission_prevents_media(self) -> None:
        value = {"planPath": "/TEST/plan", "manifestPath": "/TEST/manifest", "project": "/TEST/project"}
        with patch("ordinary_previews.require_readiness", side_effect=RuntimeError("stale")), \
                patch("ordinary_previews.readiness_packet") as packet:
            with self.assertRaisesRegex(RuntimeError, "stale"):
                _current(value)
            packet.assert_not_called()

    def test_direct_worker_cannot_render(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "live owner"):
                require_worker(Path("/TEST/request.json"), Path("/TEST/worker.py"))


if __name__ == "__main__":
    unittest.main()

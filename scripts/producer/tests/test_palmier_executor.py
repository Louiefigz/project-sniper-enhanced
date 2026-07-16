"""Executor safety: no global undo and placeholder cleanup on every exit."""
import unittest

from _common import *  # noqa: F401,F403
from palmier.executor import Executor, _overlay_groups
from palmier.mcp_client import PalmierError


class OverlayClient:
    def __init__(self, *, fail_add=False):
        self.fail_add = fail_add
        self.calls = []

    def call_json(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "add_texts":
            return {"createdTracks": [{"index": 0}],
                    "clips": [{"id": "placeholder"}]}
        if tool == "add_clips":
            if self.fail_add:
                raise PalmierError("injected placement failure")
            return {"clips": [{"id": "bad-overlay", "track": 1}],
                    "removedClipIds": ["placeholder", "human-clip"]}
        raise AssertionError(tool)

    def call(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        return "ok"


class OverlaySafetyTests(unittest.TestCase):
    def _executor(self, client):
        executor = Executor(client)
        executor.project_fps = 24
        executor.media = {"gfx:0": "media-1"}
        executor.media_s = {"gfx:0": 2.0}
        return executor

    def test_destructive_delta_removes_created_clip_never_calls_undo(self):
        client = OverlayClient()
        with self.assertRaises(PalmierError):
            self._executor(client).run({"op": "overlays", "entries": [{
                "mediaKey": "gfx:0", "startFrame": 0, "endFrame": 24}]})
        tools = [tool for tool, _args in client.calls]
        self.assertNotIn("undo", tools)
        removals = [args["clipIds"] for tool, args in client.calls
                    if tool == "remove_clips"]
        self.assertIn(["bad-overlay"], removals)
        self.assertIn(["placeholder"], removals)

    def test_placeholder_is_removed_when_placement_raises(self):
        client = OverlayClient(fail_add=True)
        with self.assertRaises(PalmierError):
            self._executor(client).run({"op": "overlays", "entries": [{
                "mediaKey": "gfx:0", "startFrame": 5, "endFrame": 24}]})
        removals = [args["clipIds"] for tool, args in client.calls
                    if tool == "remove_clips"]
        self.assertEqual(removals, [["placeholder"]])


class StackedOverlayClient:
    """Minimal delta client for overlapping overlay-track allocation."""

    def __init__(self):
        self.calls = []
        self.place_count = 0
        self.track_count = 0

    def call_json(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "add_texts":
            self.track_count += 1
            return {"createdTracks": [{"index": 0}],
                    "clips": [{"id": f"placeholder-{self.track_count}"}]}
        if tool == "add_clips":
            self.place_count += 1
            return {"clips": [{"id": f"overlay-{self.place_count}",
                                "track": 0}], "removedClipIds": []}
        raise AssertionError(tool)

    def call(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        return "ok"


class OverlayTrackAllocationTests(unittest.TestCase):
    def test_transition_preview_stacks_above_covered_graphic(self):
        groups = _overlay_groups([
            {"mediaKey": "gfx:4", "startFrame": 482, "endFrame": 592},
            {"mediaKey": "gfx:8", "startFrame": 514, "endFrame": 523},
        ])
        self.assertEqual([[index for index, _entry in group]
                          for group in groups], [[0], [1]])

    def test_overlaps_use_separate_tracks_and_preserve_plan_order(self):
        client = StackedOverlayClient()
        executor = Executor(client)
        executor.project_fps = 24
        executor.media = {f"gfx:{i}": f"media-{i}" for i in range(3)}
        executor.media_s = {f"gfx:{i}": 5.0 for i in range(3)}
        executor.run({"op": "overlays", "entries": [
            {"mediaKey": "gfx:0", "startFrame": 10, "endFrame": 20},
            {"mediaKey": "gfx:1", "startFrame": 0, "endFrame": 15},
            {"mediaKey": "gfx:2", "startFrame": 20, "endFrame": 30},
        ]})
        self.assertEqual(client.track_count, 2)
        self.assertEqual(executor.overlay_clip_ids,
                         ["overlay-3", "overlay-1", "overlay-2"])
        placements = [args for tool, args in client.calls
                      if tool == "add_clips"]
        self.assertTrue(all(row["entries"][0]["trackIndex"] == 0
                            for row in placements))


class CutClient:
    def __init__(self):
        self.calls = []
        self.next_id = 0

    def call_json(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "add_clips":
            self.next_id += 1
            return {"clips": [{"id": f"cut-{self.next_id}", "track": 1}]}
        if tool == "get_timeline":
            return {"totalFrames": 48}
        raise AssertionError(tool)

    def call(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))


class TilingCutClient(CutClient):
    def call_json(self, tool, arguments=None):
        if tool == "get_timeline":
            self.calls.append((tool, arguments or {}))
            return {"totalFrames": 35}
        return super().call_json(tool, arguments)


class ConformedCutTests(unittest.TestCase):
    def test_normalizes_each_clip_to_the_translated_frame_duration(self):
        client = CutClient()
        executor = Executor(client)
        executor.project_fps = 24
        executor.media = {"src": "media-src"}
        executor.run({"op": "cuts", "entries": [
            {"mediaKey": "src", "startFrame": 0, "endFrame": 24,
             "source": [0.0, 1.01], "speed": 1.0},
            {"mediaKey": "src", "startFrame": 24, "endFrame": 48,
             "source": [2.0, 3.0], "speed": 1.0},
        ]})
        properties = [args for tool, args in client.calls
                      if tool == "set_clip_properties"]
        self.assertEqual(properties, [
            {"clipIds": ["cut-1"], "durationFrames": 24},
            {"clipIds": ["cut-2"], "durationFrames": 24},
        ])

    def test_cut_lengths_tile_the_seam_instead_of_re_rounding_source(self):
        # Three 0.48s cuts at fps 24: source-derived lengths are round(11.52)=12
        # each, so a middle cut placed at startFrame 12 would end at 24 while the
        # next cut (translator startFrame 23) opens a 1-frame overlap. Using
        # endFrame-startFrame reproduces the translator's tiling: 12, 11, 12.
        client = TilingCutClient()
        executor = Executor(client)
        executor.project_fps = 24
        executor.media = {"src": "media-src"}
        executor.run({"op": "cuts", "entries": [
            {"mediaKey": "src", "startFrame": 0, "endFrame": 12,
             "source": [0.0, 0.48], "speed": 1.0},
            {"mediaKey": "src", "startFrame": 12, "endFrame": 23,
             "source": [1.0, 1.48], "speed": 1.0},
            {"mediaKey": "src", "startFrame": 23, "endFrame": 35,
             "source": [2.0, 2.48], "speed": 1.0},
        ]})
        durations = [args["durationFrames"] for tool, args in client.calls
                     if tool == "set_clip_properties"]
        self.assertEqual(durations, [12, 11, 12])
        self.assertEqual(executor.expected_end_frame, 35)


class MirrorClient:
    def __init__(self, total=300, removed=None):
        self.total = total
        self.removed = removed or []
        self.calls = []

    def call_json(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "add_clips":
            return {"clips": [{"id": "mirror-1", "track": 1}],
                    "removedClipIds": self.removed}
        if tool == "get_timeline":
            return {"totalFrames": self.total}
        raise AssertionError(tool)


class VisualMirrorTests(unittest.TestCase):
    def _executor(self, client):
        executor = Executor(client)
        executor.project_fps = 30
        executor.media = {"master": "master-ref"}
        executor.media_s = {"master": 10.0}
        return executor

    def test_places_exactly_one_full_master_clip(self):
        client = MirrorClient()
        executor = self._executor(client)
        executor.run({"op": "mirror", "entry": {
            "mediaKey": "master", "source": [0.0, 10.0],
            "endFrame": 300, "masterHash": "abc"}})
        self.assertEqual(executor.mirror_clip_ids, ["mirror-1"])
        placement = client.calls[0][1]["entries"][0]
        self.assertEqual(placement, {"mediaRef": "master-ref",
                                     "startFrame": 0,
                                     "source": [0.0, 10.0]})

    def test_frame_or_destructive_delta_mismatch_fails_closed(self):
        step = {"op": "mirror", "entry": {
            "mediaKey": "master", "source": [0.0, 10.0],
            "endFrame": 300, "masterHash": "abc"}}
        with self.assertRaisesRegex(PalmierError, "frame mismatch"):
            self._executor(MirrorClient(total=299)).run(step)
        with self.assertRaisesRegex(PalmierError, "non-destructive"):
            self._executor(MirrorClient(removed=["human"])).run(step)


if __name__ == "__main__":
    unittest.main()

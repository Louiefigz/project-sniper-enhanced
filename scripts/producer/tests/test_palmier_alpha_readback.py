"""Adversarial current-readback and production z-order alpha tests."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from _common import *  # noqa: F401,F403
from palmier.desktop_caption_pages import require_caption_pages_ready
from palmier.desktop_caption_shard_plan import FULL_CANVAS_TRANSFORM
from palmier.desktop_caption_shards import (
    require_graphics_shards_ready, require_title_shards_ready,
)
from palmier.desktop_manifest import _ordered_visual_layers
from palmier.desktop_manifest import _broll_steps
from palmier.desktop_visual_stack import require_visual_stack
from palmier.mcp_client import PalmierError


def _row(op: str, lane: str, ident: str, start: int, end: int) -> dict:
    return {
        "op": op, "lane": lane, "elementId": ident,
        "mediaKey": f"key-{ident}", "assetPath": f"/tmp/{ident}.mov",
        "assetHash": ident[0] * 64, "startFrame": start, "endFrame": end,
        "transform": dict(FULL_CANVAS_TRANSFORM),
    }


def _fixture(rows: list[dict], shared: bool = False) -> tuple[dict, dict]:
    tracks = [{"type": "video", "clips": []} for _row in rows]
    elements, media = {}, {}
    for index, row in enumerate(rows):
        track = 0 if shared else len(rows) - index - 1
        clip_id, ref = f"clip-{row['elementId']}", f"ref-{row['elementId']}"
        tracks[track]["clips"].append({
            "id": clip_id, "mediaRef": ref, "mediaType": "video",
            "frames": [row["startFrame"], row["endFrame"]],
            "transform": dict(row["transform"]),
        })
        elements[row["elementId"]] = {
            "status": "current", "lane": row["lane"], "clipId": clip_id,
            "mediaRef": ref, "assetHash": row["assetHash"],
            "assetPath": row["assetPath"], "startFrame": row["startFrame"],
            "endFrame": row["endFrame"], "trackIndex": track,
            "transform": dict(row["transform"]),
        }
        media[row["assetHash"]] = {"mediaRef": ref}
    state = {"elementLedger": {"elements": elements}, "mediaLedger": media}
    timeline = {"tracks": tracks}
    return state, timeline


class AlphaReadbackTests(unittest.TestCase):
    def _state(self, rows: list[dict], shared: bool = False) -> tuple:
        state, timeline = _fixture(rows, shared)
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name, "operations.json")
        steps = [{"op": "caption-alpha-pages", "lane": "captions-alpha",
                  "entries": rows}] if shared else rows
        path.write_text(json.dumps({"steps": steps}))
        state["operations"] = {"path": str(path)}
        return temp, state, timeline

    def test_title_and_graphics_require_live_unique_dedicated_clips(self):
        cases = (
            ("title-alpha-shard", "title-cards-alpha",
             require_title_shards_ready),
            ("graphics-alpha-shard", "graphics",
             require_graphics_shards_ready),
        )
        for op, lane, checker in cases:
            rows = [_row(op, lane, "a", 0, 10),
                    _row(op, lane, "b", 4, 14)]
            temp, state, timeline = self._state(rows)
            with temp:
                self.assertEqual(checker(state, timeline)["tracks"], [1, 0])
                missing = copy.deepcopy(timeline)
                missing["tracks"][1]["clips"] = []
                with self.assertRaisesRegex(PalmierError, "current clip"):
                    checker(state, missing)
                same_track = copy.deepcopy(timeline)
                same_track["tracks"][0]["clips"].extend(
                    same_track["tracks"][1]["clips"])
                same_track["tracks"][1]["clips"] = []
                with self.assertRaisesRegex(PalmierError, "topology"):
                    checker(state, same_track)

    def test_caption_pages_reject_deletion_media_window_and_duplicate_ids(self):
        rows = [_row("page", "captions-alpha", "a", 0, 10),
                _row("page", "captions-alpha", "b", 10, 20)]
        temp, state, timeline = self._state(rows, True)
        with temp:
            self.assertEqual(require_caption_pages_ready(
                state, timeline)["trackIndex"], 0)
            mutations = []
            missing = copy.deepcopy(timeline)
            missing["tracks"][0]["clips"].pop()
            mutations.append(missing)
            media = copy.deepcopy(timeline)
            media["tracks"][0]["clips"][0]["mediaRef"] = "drift"
            mutations.append(media)
            window = copy.deepcopy(timeline)
            window["tracks"][0]["clips"][0]["frames"] = [1, 10]
            mutations.append(window)
            duplicate = copy.deepcopy(state)
            duplicate["elementLedger"]["elements"]["b"]["clipId"] = \
                duplicate["elementLedger"]["elements"]["a"]["clipId"]
            for changed in mutations:
                with self.assertRaises(PalmierError):
                    require_caption_pages_ready(state, changed)
            with self.assertRaisesRegex(PalmierError, "identities"):
                require_caption_pages_ready(duplicate, timeline)

    def test_manifest_and_final_readback_match_production_z_order(self):
        rows = _ordered_visual_layers([[
            {"op": "graphics-alpha-shard"},
            {"op": "native-broll"},
            {"op": "caption-alpha-pages"},
            {"op": "title-alpha-shard"},
        ]])
        self.assertEqual([row["op"] for row in rows], [
            "native-broll", "title-alpha-shard",
            "graphics-alpha-shard", "caption-alpha-pages"])
        state = {"elementLedger": {"elements": {}}}
        lanes = ("captions-alpha", "graphics", "title-cards-alpha", "broll")
        tracks = []
        for index, lane in enumerate(lanes):
            ident = f"{lane}-clip"
            tracks.append({"type": "video", "clips": [{
                "id": ident, "mediaType": "video", "frames": [0, 10]}]})
            state["elementLedger"]["elements"][lane] = {
                "status": "current", "lane": lane, "clipId": ident}
        tracks.append({"type": "video", "clips": [{
            "id": "base", "mediaType": "video", "frames": [0, 10]}]})
        timeline = {"tracks": tracks}
        self.assertTrue(require_visual_stack(state, timeline)["proved"])
        timeline["tracks"][1], timeline["tracks"][3] = (
            timeline["tracks"][3], timeline["tracks"][1])
        with self.assertRaisesRegex(PalmierError, "z-order"):
            require_visual_stack(state, timeline)

    def test_broll_focus_ops_fail_before_the_live_worklist(self):
        with self.assertRaisesRegex(PalmierError, "no exact Palmier"):
            _broll_steps({
                "brollTrack": [{
                    "assetId": "b1", "outStart": 0, "outEnd": 1,
                    "focusOps": [{"op": "pan"}],
                }],
            }, {"broll": [{"id": "b1", "path": "/tmp/broll.mp4"}]},
                30.0, "/tmp")


if __name__ == "__main__":
    unittest.main()

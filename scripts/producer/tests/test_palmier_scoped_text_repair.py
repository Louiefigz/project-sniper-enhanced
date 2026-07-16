"""Scoped native-text repair contracts for Desktop Palmier."""
import json
import os
import tempfile
import unittest

from _common import *  # noqa: F401,F403
from palmier.desktop_text import (build_text_addition_repair,
                                  exact_text_addition, observe_texts,
                                  text_add_binding)
from palmier.mcp_client import PalmierError


def _plan(titles=None, graphic_text="Same"):
    return {
        "cutTrack": [{"sourceId": "src", "start": 0, "end": 10}],
        "graphicsTrack": [{"id": "g1", "spec": {"text": graphic_text}}],
        "titleCards": [],
        "persistentText": titles or [],
    }


def _banner(end=10.0):
    return {
        "id": "ai-edit-banner", "text": "Entirely Edited with AI",
        "outStart": 0.0, "outEnd": end, "persistent": True,
        "fontName": "Inter", "fontSize": 52, "color": "#111111",
        "backgroundColor": "#FFFFFF", "isBold": True,
        "alignment": "center", "animation": "off",
        "transform": {"centerX": 0.5, "centerY": 0.035,
                      "width": 1.0, "height": 0.07},
    }


def _timeline(track_rows):
    return {"tracks": track_rows}


class ScopedTextPlanTests(unittest.TestCase):
    def test_banner_addition_is_exact_full_timeline_work(self):
        steps = build_text_addition_repair(
            _plan(), _plan([_banner()]), 24.0, 240)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["op"], "native-text-add")
        self.assertEqual(steps[0]["trackPolicy"], "new-top-video-track")
        item = steps[0]["items"][0]
        self.assertEqual(item["elementId"], "ai-edit-banner")
        self.assertEqual((item["entry"]["startFrame"],
                          item["entry"]["endFrame"]), (0, 240))
        self.assertNotIn("trackIndex", item["entry"])

    def test_persistent_banner_must_cover_the_candidate(self):
        with self.assertRaisesRegex(PalmierError, "span the full timeline"):
            build_text_addition_repair(
                _plan(), _plan([_banner(9.0)]), 24.0, 240)

    def test_text_repair_rejects_other_lane_or_existing_text_changes(self):
        with self.assertRaisesRegex(PalmierError, "other lanes: graphicsTrack"):
            build_text_addition_repair(
                _plan(), _plan([_banner()], "Changed"), 24.0, 240)
        old = _plan([_banner()])
        edited = _banner()
        edited["text"] = "Different"
        with self.assertRaisesRegex(PalmierError, "cannot update existing"):
            build_text_addition_repair(old, _plan([edited]), 24.0, 240)


class ScopedTextBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.operations = os.path.join(self.tmp.name, "operations.json")
        self.entry = {
            "startFrame": 0, "endFrame": 240,
            "content": "Entirely Edited with AI",
            "transform": {"centerX": 0.5, "centerY": 0.035,
                          "width": 1.0, "height": 0.07},
        }
        self.item = {"elementId": "ai-edit-banner", "textHash": "a" * 64,
                     "entry": self.entry}
        with open(self.operations, "w", encoding="utf-8") as handle:
            json.dump({"steps": [{"op": "native-text-add",
                                   "items": [self.item]}]}, handle)
        self.state = {"operations": {"path": self.operations},
                      "elementLedger": {"schemaVersion": 1, "elements": {}}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_args_bind_and_top_track_readback_updates_ledger(self):
        args = {"entries": [self.entry]}
        exact_text_addition(self.state, args)
        binding = text_add_binding(args, self.state)
        base = {"id": "base", "frames": [0, 240], "mediaRef": "src"}
        text_clip = {"id": "banner", "frames": [0, 240], "mediaRef": "",
                     "mediaType": "text",
                     "textContent": "Entirely Edited with AI"}
        before = _timeline([{"clips": [base]}])
        after = _timeline([{"clips": [text_clip]}, {"clips": [base]}])
        observe_texts(self.state, binding, before, after)
        row = self.state["elementLedger"]["elements"]["ai-edit-banner"]
        self.assertEqual((row["clipId"], row["trackIndex"]), ("banner", 0))

    def test_mismatched_style_or_unrelated_addition_fails_closed(self):
        with self.assertRaisesRegex(PalmierError, "differs from"):
            exact_text_addition(self.state, {"entries": [{**self.entry,
                                                           "fontSize": 60}]})
        binding = text_add_binding({"entries": [self.entry]}, self.state)
        before = _timeline([{"clips": []}])
        text_clip = {"id": "banner", "frames": [0, 240], "mediaRef": "",
                     "textContent": "Entirely Edited with AI"}
        extra = {"id": "extra", "frames": [0, 10], "mediaRef": "other"}
        after = _timeline([{"clips": [text_clip, extra]}])
        with self.assertRaisesRegex(PalmierError, "unrelated clip"):
            observe_texts(self.state, binding, before, after)


if __name__ == "__main__":
    unittest.main()

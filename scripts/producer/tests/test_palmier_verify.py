"""Palmier generated-timeline structural verification tests."""
import copy
import unittest
from types import SimpleNamespace

from _common import *  # noqa: F401,F403
from palmier.mcp_client import PalmierError
from palmier.verify import verify_generated_timeline


ROWS = [[0, 1.0, 1.0, "smooth"], [12, 1.2, 1.2, "smooth"]]


def _lanes() -> dict:
    return {
        "cuts": {"entries": [
            {"mediaKey": "src", "source": [0.0, 1.0],
             "startFrame": 0, "endFrame": 24, "speed": 1.0},
            {"mediaKey": "src", "source": [2.0, 3.0],
             "startFrame": 24, "endFrame": 48, "speed": 1.0},
        ]},
        "overlays": {"entries": [
            {"mediaKey": "gfx:0", "startFrame": 5, "endFrame": 20},
        ]},
        "texts": [
            {"content": "HOOK", "startFrame": 2, "endFrame": 12},
        ],
        "keyframes": [
            {"op": "keyframes", "clip": 0, "property": "scale",
             "rows": ROWS},
        ],
    }


def _executor():
    return SimpleNamespace(
        cut_clip_ids=["cut-1", "cut-2"],
        overlay_clip_ids=["gfx-1"],
        text_clip_ids=["text-1"],
        music_clip_ids=[],
        project_fps=24,
        expected_end_frame=48,
        media={"src": "media-src", "gfx:0": "media-gfx"},
        media_s={"src": 8.0, "gfx:0": 2.0},
    )


def _timeline() -> dict:
    return {
        "id": "shadow",
        "totalFrames": 48,
        "tracks": [
            {"type": "video", "clips": [
                {"id": "gfx-1", "frames": [5, 20],
                 "mediaRef": "media-gfx"},
            ]},
            {"type": "video", "clips": [
                {"id": "cut-1", "frames": [0, 24],
                 "mediaRef": "media-src", "trimEndFrame": 168,
                 "keyframes": {"scale": ROWS}},
                {"id": "cut-2", "frames": [24, 48],
                 "mediaRef": "media-src", "trimStartFrame": 48,
                 "trimEndFrame": 120},
            ]},
            {"type": "text", "clips": [
                {"id": "text-1", "frames": [2, 12],
                 "textContent": "HOOK"},
            ]},
        ],
    }


def _mirror_lanes() -> dict:
    return {"mirror": {"entry": {"mediaKey": "master", "startFrame": 0,
                                    "endFrame": 300, "masterHash": "abc"}},
            "keyframes": []}


def _mirror_executor():
    return SimpleNamespace(
        mirror_clip_ids=["mirror-1"], cut_clip_ids=[], overlay_clip_ids=[],
        text_clip_ids=[], music_clip_ids=[], project_fps=30,
        expected_end_frame=300, media={"master": "master-ref"},
        media_s={"master": 10.0})


class TimelineClient:
    def __init__(self, timeline: dict):
        self.timeline = timeline

    def call_json(self, tool, arguments=None):
        if tool != "get_timeline":
            raise AssertionError(tool)
        return self.timeline


class TimelineVerificationTests(unittest.TestCase):
    def verify(self, timeline: dict) -> dict:
        return verify_generated_timeline(
            TimelineClient(timeline), "shadow", _lanes(), _executor())

    def test_exact_structure_and_keyframes_verify(self):
        result = self.verify(_timeline())
        self.assertTrue(result["ok"])
        self.assertEqual(result["expected"], result["actual"])
        self.assertEqual(result["expected"]["counts"], {
            "cuts": 2, "overlays": 1, "texts": 1})
        self.assertEqual(result["keyframes"], {
            "status": "verified", "easing": "verified", "properties": 1})

    def test_keyframe_values_verify_when_palmier_omits_easing_labels(self):
        timeline = _timeline()
        timeline["tracks"][1]["clips"][0]["keyframes"] = {
            "scale": [row[:-1] for row in ROWS]}
        result = self.verify(timeline)
        self.assertEqual(result["keyframes"], {
            "status": "verified-values", "easing": "not_exposed",
            "properties": 1})

    def test_required_keyframes_fail_when_mcp_omits_them(self):
        timeline = _timeline()
        timeline["tracks"][1]["clips"][0].pop("keyframes")
        with self.assertRaisesRegex(
                PalmierError, "required keyframe properties were not exposed"):
            self.verify(timeline)

    def test_readback_proves_material_rightward_face_pan(self):
        lanes = _lanes()
        scale = [[0, 1.0, 1.0, "smooth"],
                 [12, 1.2274, 1.2274, "smooth"]]
        position = [[0, 0.0, 0.0, "smooth"],
                    [12, -0.0101, -0.0864, "smooth"]]
        lanes["keyframes"] = [
            {"op": "keyframes", "clip": 0, "property": "scale",
             "rows": scale},
            {"op": "keyframes", "clip": 0, "property": "position",
             "rows": position},
        ]
        timeline = _timeline()
        timeline["tracks"][1]["clips"][0]["keyframes"] = {
            "scale": scale, "position": position}
        result = verify_generated_timeline(
            TimelineClient(timeline), "shadow", lanes, _executor())
        self.assertEqual(result["keyframes"]["properties"], 2)
        landed_face_x = 0.55 * scale[-1][1] + position[-1][1]
        self.assertGreater(landed_face_x, 0.65)
        timeline["tracks"][1]["clips"][0]["keyframes"].pop("position")
        with self.assertRaisesRegex(PalmierError, "position keyframes differ"):
            verify_generated_timeline(
                TimelineClient(timeline), "shadow", lanes, _executor())

    def test_timing_mismatch_fails_closed(self):
        timeline = _timeline()
        timeline["tracks"][0]["clips"][0]["frames"] = [5, 19]
        with self.assertRaisesRegex(PalmierError, "occupies"):
            self.verify(timeline)

    def test_total_frame_mismatch_fails_closed(self):
        timeline = _timeline()
        timeline["totalFrames"] = 47
        with self.assertRaisesRegex(PalmierError, "totalFrames"):
            self.verify(timeline)

    def test_missing_expected_clip_fails_closed(self):
        timeline = _timeline()
        timeline["tracks"][2]["clips"] = []
        with self.assertRaisesRegex(PalmierError, "missing texts clip"):
            self.verify(timeline)

    def test_unexpected_placeholder_fails_closed(self):
        timeline = copy.deepcopy(_timeline())
        timeline["tracks"][0]["clips"].append({
            "id": "placeholder", "frames": [0, 1], "textContent": "."})
        with self.assertRaisesRegex(PalmierError, "unexpected clips"):
            self.verify(timeline)

    def test_source_trim_allows_one_conformed_frame_but_not_two(self):
        timeline = _timeline()
        timeline["tracks"][1]["clips"][1]["trimStartFrame"] = 47
        result = self.verify(timeline)
        self.assertTrue(result["ok"])
        timeline["tracks"][1]["clips"][1]["trimStartFrame"] = 46
        with self.assertRaisesRegex(PalmierError, "trimStartFrame"):
            self.verify(timeline)

    def test_cut_boundaries_allow_one_conformed_frame_when_seams_stay_closed(self):
        timeline = _timeline()
        timeline["tracks"][1]["clips"][0]["frames"] = [0, 25]
        timeline["tracks"][1]["clips"][1]["frames"] = [25, 48]
        result = self.verify(timeline)
        self.assertTrue(result["ok"])

    def test_cut_boundary_tolerance_never_allows_gap_or_overlap(self):
        timeline = _timeline()
        timeline["tracks"][1]["clips"][0]["frames"] = [0, 25]
        with self.assertRaisesRegex(PalmierError, "gap or overlap"):
            self.verify(timeline)

    def test_two_frame_cut_boundary_drift_fails_closed(self):
        timeline = _timeline()
        timeline["tracks"][1]["clips"][0]["frames"] = [0, 26]
        timeline["tracks"][1]["clips"][1]["frames"] = [26, 48]
        with self.assertRaisesRegex(PalmierError, "occupies"):
            self.verify(timeline)

    def test_source_media_identity_must_match(self):
        timeline = _timeline()
        timeline["tracks"][1]["clips"][0]["mediaRef"] = "wrong"
        with self.assertRaisesRegex(PalmierError, "wrong media"):
            self.verify(timeline)

    def test_baseline_transform_must_match(self):
        lanes = _lanes()
        lanes["baseline"] = {"transform": {
            "width": 1.1, "height": 1.1, "centerX": 0.5, "centerY": 0.45}}
        timeline = _timeline()
        for clip in timeline["tracks"][1]["clips"]:
            clip["transform"] = dict(lanes["baseline"]["transform"])
        result = verify_generated_timeline(
            TimelineClient(timeline), "shadow", lanes, _executor())
        self.assertTrue(result["ok"])
        timeline["tracks"][1]["clips"][0]["transform"]["width"] = 1.0
        with self.assertRaisesRegex(PalmierError, "transform.width"):
            verify_generated_timeline(
                TimelineClient(timeline), "shadow", lanes, _executor())


class VisualMirrorVerificationTests(unittest.TestCase):
    def timeline(self, media_ref="master-ref", end=300, extras=None):
        clips = [{"id": "mirror-1", "frames": [0, end],
                  "mediaRef": media_ref, "mediaType": "video"}]
        clips.extend(extras or [])
        return {"id": "shadow", "totalFrames": end,
                "tracks": [{"type": "video", "clips": clips}]}

    def verify(self, timeline):
        return verify_generated_timeline(
            TimelineClient(timeline), "shadow", _mirror_lanes(),
            _mirror_executor())

    def test_single_master_clip_proves_identity_and_frames(self):
        result = self.verify(self.timeline())
        self.assertTrue(result["ok"])
        self.assertEqual(result["expected"]["counts"], {"mirror": 1})
        self.assertEqual(result["visualMaster"], {
            "mediaRef": "master-ref", "masterHash": "abc",
            "singleVisibleClip": True})

    def test_wrong_master_or_visible_extra_fails_closed(self):
        with self.assertRaisesRegex(PalmierError, "wrong media"):
            self.verify(self.timeline(media_ref="other"))
        extra = {"id": "old-graphic", "frames": [0, 30],
                 "mediaRef": "graphic", "mediaType": "video"}
        with self.assertRaisesRegex(PalmierError, "unexpected clips"):
            self.verify(self.timeline(extras=[extra]))


if __name__ == "__main__":
    unittest.main()

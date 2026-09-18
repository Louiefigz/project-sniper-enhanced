"""palmier sync tests — lane diffing, content keys, step parsing (pure).

The incremental-push contract: ONLY the lane the operator changed re-syncs;
media identity is CONTENT (source hash / render-cache hash), never import
order; unknown step vocabulary fails loud.
"""
import json
import os
import tempfile
import unittest

from _common import *  # noqa: F401,F403
from palmier.mcp_client import PalmierError
from palmier.shadow import SyncRequest
from palmier.sync import (_is_current, content_key, lane_fingerprints,
                          parse_steps, plan_content_hash)
from palmier.translate import TranslateRequest, translate

SRC_HASH = "abc123"
EXACT_PARITY = {"schemaVersion": 1, "fullyEditable": True}
PUSH = {"outStart": 1.0, "outEnd": 3.0, "zoom": 1.2,
        "attackS": 0.25, "releaseS": 0.25}


def _steps(plan_extra=None, gfx_paths=None):
    plan = {"target": {"mode": "longform"},
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 10.0}],
            "captions": {"burn": False}, **(plan_extra or {})}
    request = TranslateRequest(
        fps=24.0, source_path="/src.mp4", graphics_paths=gfx_paths or {},
        project_name="t", width=1920, height=1080,
        export_path="/out.mp4")
    return translate(plan, request)


class ParseStepsTests(unittest.TestCase):
    def test_groups_every_lane(self) -> None:
        lanes = parse_steps(_steps(
            {"punchIns": [dict(PUSH)],
             "graphicsTrack": [{"kind": "stat-card", "outStart": 1.0,
                                "outEnd": 3.0}],
             "titleCards": [{"text": "HOOK", "outStart": 0.0, "outEnd": 2.0}],
             "music": {"enabled": True, "path": "/bed.mp3"}},
            gfx_paths={0: "/cache/deadbeef.mov"}))
        self.assertIsNotNone(lanes["cuts"])
        self.assertEqual(len(lanes["keyframes"]), 2)   # scale + position
        self.assertEqual(len(lanes["overlays"]["entries"]), 1)
        self.assertEqual(len(lanes["texts"]), 1)
        self.assertIsNone(lanes["music"])
        self.assertTrue(any("preview-silent" in step["message"]
                            for step in lanes["warns"]))
        self.assertIsNotNone(lanes["export"])
        self.assertEqual(set(lanes["imports"]), {"src", "gfx:0"})

    def test_unknown_op_fails_loud(self) -> None:
        with self.assertRaises(PalmierError):
            parse_steps([{"op": "mystery"}])


class ContentKeyTests(unittest.TestCase):
    def test_source_keyed_by_manifest_hash(self) -> None:
        self.assertEqual(content_key("src", "/any/path.mp4", SRC_HASH),
                         f"src:{SRC_HASH}")

    def test_graphic_keyed_by_render_cache_hash(self) -> None:
        self.assertEqual(content_key("gfx:3", "/cache/deadbeef.mov", SRC_HASH),
                         "gfx:deadbeef.mov")


class PlanHashTests(unittest.TestCase):
    def test_version_and_graphic_addressing_do_not_create_false_staleness(self):
        base = {"planVersion": 1, "cutTrack": [{"start": 0.0, "end": 2.0}],
                "graphicsTrack": [{"id": "g-1", "kind": "card", "spec": {"n": 1}}]}
        saved = {**base, "planVersion": 99,
                 "graphicsTrack": [{**base["graphicsTrack"][0], "id": "g-2"}]}
        self.assertEqual(plan_content_hash(base), plan_content_hash(saved))

    def test_render_content_change_moves_the_hash(self):
        base = {"cutTrack": [{"start": 0.0, "end": 2.0}]}
        edited = {"cutTrack": [{"start": 0.0, "end": 3.0}]}
        self.assertNotEqual(plan_content_hash(base), plan_content_hash(edited))


class CurrentExportTests(unittest.TestCase):
    def test_sync_requires_verified_authoritative_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = SyncRequest(tmp, "src", "plan-hash", EXACT_PARITY,
                                  authority_hash="authority-hash")
            lane_fp = {"cuts": "same"}
            sidecar = {"lastPushPlanHash": "plan-hash", "laneFp": lane_fp}
            with open(os.path.join(tmp, "final.palmier.mp4"), "wb"):
                pass
            meta_path = os.path.join(tmp, "final.palmier.meta.json")
            with open(meta_path, "w") as handle:
                json.dump({"planHash": "plan-hash", "exportVerified": True}, handle)
            self.assertFalse(_is_current(request, lane_fp, sidecar))
            with open(meta_path, "w") as handle:
                json.dump({"planHash": "plan-hash", "exportVerified": True,
                           "audioVerified": True}, handle)
            self.assertFalse(_is_current(request, lane_fp, sidecar))
            with open(meta_path, "w") as handle:
                json.dump({"planHash": "plan-hash", "exportVerified": True,
                           "audioVerified": True,
                           "authorityHash": "authority-hash"}, handle)
            self.assertFalse(_is_current(request, lane_fp, sidecar))
            sidecar.update({
                "parity": EXACT_PARITY,
                "latestTimelineId": "generated",
                "verification": {"ok": True, "timelineId": "generated",
                                 "expected": {}, "actual": {}},
            })
            self.assertTrue(_is_current(request, lane_fp, sidecar))


class LaneDiffTests(unittest.TestCase):
    """A plan edit must move EXACTLY its own lane's fingerprint."""

    BASE = {"punchIns": [dict(PUSH)],
            "graphicsTrack": [{"kind": "stat-card", "outStart": 1.0,
                               "outEnd": 3.0, "spec": {"title": "A"}}]}

    def _fp(self, plan_extra, gfx_path="/cache/aaaa.mov"):
        lanes = parse_steps(_steps(plan_extra, gfx_paths={0: gfx_path}))
        return lane_fingerprints(lanes, SRC_HASH)

    def test_identical_plans_have_identical_fingerprints(self) -> None:
        self.assertEqual(self._fp(self.BASE), self._fp(self.BASE))

    def test_graphic_spec_change_moves_only_gfx(self) -> None:
        # a spec edit lands as a NEW render hash (content-hash cache)
        a, b = self._fp(self.BASE), self._fp(self.BASE, "/cache/bbbb.mov")
        moved = {k for k in a if a[k] != b[k]}
        self.assertEqual(moved, {"gfx"})

    def test_punch_change_moves_only_motion(self) -> None:
        edited = {**self.BASE,
                  "punchIns": [{**PUSH, "zoom": 1.4}]}
        a, b = self._fp(self.BASE), self._fp(edited)
        self.assertEqual({k for k in a if a[k] != b[k]}, {"motion"})

    def test_cut_change_moves_cuts_and_time_dependent_lanes(self) -> None:
        edited = {**self.BASE,
                  "cutTrack": [{"sourceId": "raw-1", "start": 0.0,
                                "end": 8.0}]}
        lanes = parse_steps(_steps(edited, gfx_paths={0: "/cache/aaaa.mov"}))
        a, b = self._fp(self.BASE), lane_fingerprints(lanes, SRC_HASH)
        self.assertIn("cuts", {k for k in a if a[k] != b[k]})

    def test_source_content_change_moves_cuts(self) -> None:
        lanes = parse_steps(_steps(self.BASE,
                                   gfx_paths={0: "/cache/aaaa.mov"}))
        a = lane_fingerprints(lanes, SRC_HASH)
        b = lane_fingerprints(lanes, "different-source")
        self.assertIn("cuts", {k for k in a if a[k] != b[k]})


if __name__ == "__main__":
    unittest.main()

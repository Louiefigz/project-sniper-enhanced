"""Fail-closed validation for controller-authored Palmier native plans."""
import copy
import unittest

from _common import *  # noqa: F401,F403
from palmier.mcp_client import PalmierError
from palmier.native_plan import remap_plan_ids, validate_native_plan
from palmier.timeline_authority import snapshot


def _timeline() -> dict:
    return {
        "id": "head", "name": "Manual head", "fps": 24,
        "width": 1920, "height": 1080, "totalFrames": 120,
        "tracks": [{"id": "track-1", "index": 0, "type": "video",
                    "clips": [{"id": "clip-1", "frames": [0, 120],
                               "mediaRef": "asset-1",
                               "audio": {"id": "audio-1", "volume": 1}}]}],
    }


def _authority() -> dict:
    found = snapshot("project-1", _timeline())
    return {"projectId": found.project_id, "timelineId": found.timeline_id,
            "fingerprint": found.fingerprint, "timeline": found.timeline}


def _plan(authority: dict) -> dict:
    return {
        "schemaVersion": 1,
        "parent": {key: authority[key] for key in
                   ("projectId", "timelineId", "fingerprint")},
        "requestHash": "a" * 64,
        "lanes": ["graphics", "motion"],
        "operations": [{
            "tool": "set_clip_properties",
            "args": {"clipIds": ["clip-1"], "opacity": 0.5},
            "reason": "Let the full-frame statement stay readable",
        }],
    }


class NativePlanTests(unittest.TestCase):
    def test_multiple_unique_lanes_and_known_ids_are_valid(self):
        authority = _authority()
        self.assertEqual(validate_native_plan(_plan(authority), authority),
                         _plan(authority))

    def test_singular_duplicate_and_unknown_lanes_fail_closed(self):
        authority = _authority()
        singular = _plan(authority)
        singular["lane"] = singular.pop("lanes")[0]
        duplicate = _plan(authority)
        duplicate["lanes"] = ["cuts", "cuts"]
        unknown = _plan(authority)
        unknown["lanes"] = ["titles"]
        for value in (singular, duplicate, unknown):
            with self.subTest(value=value.get("lanes", value.get("lane"))):
                with self.assertRaises(PalmierError):
                    validate_native_plan(value, authority)

    def test_stale_parent_forbidden_tool_and_unknown_id_are_rejected(self):
        authority = _authority()
        stale = _plan(authority)
        stale["parent"]["fingerprint"] = "0" * 64
        forbidden = _plan(authority)
        forbidden["operations"][0]["tool"] = "import_media"
        unknown = _plan(authority)
        unknown["operations"][0]["args"]["clipIds"] = ["missing"]
        for value in (stale, forbidden, unknown):
            with self.assertRaises(PalmierError):
                validate_native_plan(value, authority)

    def test_unknown_arguments_and_boolean_numbers_are_rejected(self):
        authority = _authority()
        smuggled = _plan(authority)
        smuggled["operations"][0]["args"]["mediaRef"] = "/tmp/file.mp4"
        boolean = _plan(authority)
        boolean["operations"][0]["args"]["opacity"] = True
        for value in (smuggled, boolean):
            with self.assertRaises(PalmierError):
                validate_native_plan(value, authority)

    def test_lane_mismatch_and_out_of_range_keyframe_are_rejected(self):
        authority = _authority()
        mislabeled = _plan(authority)
        mislabeled["lanes"] = ["cuts"]
        keyframe = _plan(authority)
        keyframe["operations"] = [{
            "tool": "set_keyframes",
            "args": {"clipId": "clip-1", "property": "opacity",
                     "keyframes": [[121, 1]]},
            "reason": "A restrained emphasis",
        }]
        for value in (mislabeled, keyframe):
            with self.assertRaises(PalmierError):
                validate_native_plan(value, authority)

    def test_remap_translates_scalar_and_list_structural_references(self):
        authority = _authority()
        plan = _plan(authority)
        plan["operations"].append({
            "tool": "set_keyframes",
            "args": {"clipId": "clip-1", "property": "opacity",
                     "keyframes": [[0, 0], [12, 1]]},
            "reason": "Earn one restrained entrance",
        })
        remapped = remap_plan_ids(copy.deepcopy(plan), {"clip-1": "clip-copy"})
        self.assertEqual(remapped["operations"][0]["args"]["clipIds"],
                         ["clip-copy"])
        self.assertEqual(remapped["operations"][1]["args"]["clipId"],
                         "clip-copy")


if __name__ == "__main__":
    unittest.main()

"""Pre-critic Palmier-native craft and safety gate contracts."""
import copy
import hashlib
import unittest

from _common import *  # noqa: F401,F403
from palmier.mcp_client import PalmierError
from palmier.native_gate import validate_native_gate
from palmier.timeline_authority import snapshot

REQUEST = "Make the requested Palmier timeline change"


def _timeline() -> dict:
    return {
        "id": "head", "name": "Manual head", "fps": 24,
        "width": 1920, "height": 1080, "totalFrames": 120,
        "tracks": [
            {"id": "video-track", "index": 0, "type": "video",
             "clips": [{"id": "clip-1", "frames": [0, 120],
                        "mediaRef": "asset-1",
                        "audio": {"id": "audio-1", "volume": 1}}]},
            {"id": "text-track", "index": 1, "type": "text",
             "clips": [{"id": "text-1", "frames": [12, 48],
                        "textContent": "Existing"}]},
        ],
    }


def _authority() -> dict:
    found = snapshot("project-1", _timeline())
    return {"projectId": found.project_id, "timelineId": found.timeline_id,
            "fingerprint": found.fingerprint, "timeline": found.timeline}


def _plan(authority: dict, operation: dict, lanes: list[str]) -> dict:
    return {
        "schemaVersion": 1,
        "parent": {key: authority[key] for key in
                   ("projectId", "timelineId", "fingerprint")},
        "requestHash": hashlib.sha256(REQUEST.encode()).hexdigest(),
        "lanes": lanes, "operations": [operation],
    }


def _op(tool: str, args: dict) -> dict:
    return {"tool": tool, "args": args,
            "reason": "Apply only the operator-requested native delta"}


def _reject(plan: dict, authority: dict, pattern: str | None = None) -> None:
    context = unittest.TestCase()
    manager = context.assertRaisesRegex(PalmierError, pattern) if pattern \
        else context.assertRaises(PalmierError)
    with manager:
        validate_native_gate(plan, authority, REQUEST, plan["lanes"])


class NativeGateTests(unittest.TestCase):
    def test_valid_motion_text_and_audio_operations_pass(self):
        authority = _authority()
        operations = [
            (_op("set_keyframes", {"clipId": "clip-1", "property": "scale",
                                    "keyframes": [[0, 1.0], [6, 1.1]]}), ["motion"]),
            (_op("add_texts", {"entries": [{"content": "Clear card",
                                              "startFrame": 20, "endFrame": 40}]}), ["graphics"]),
            (_op("denoise_audio", {"clipIds": ["audio-1"],
                                    "enabled": True, "strength": 0.4}), ["audio"]),
        ]
        for operation, lanes in operations:
            with self.subTest(tool=operation["tool"]):
                plan = _plan(authority, operation, lanes)
                self.assertEqual(validate_native_gate(
                    plan, authority, REQUEST, lanes), plan)

    def test_linked_av_targets_and_sync_lock_bypass_fail(self):
        authority = _authority()
        values = [
            _plan(authority, _op("denoise_audio", {
                "clipIds": ["clip-1"], "strength": 0.5}), ["audio"]),
            _plan(authority, _op("denoise_audio", {
                "clipIds": ["audio-1"], "enabled": "yes"}), ["audio"]),
            _plan(authority, _op("set_clip_properties", {
                "clipIds": ["clip-1"], "volume": 0.5}), ["audio"]),
            _plan(authority, _op("update_text", {
                "clipIds": ["clip-1"], "content": "Wrong target"}), ["captions"]),
            _plan(authority, _op("ripple_delete_ranges", {
                "clipId": "clip-1", "ranges": [[10, 20]], "units": "frames",
                "ignoreSyncLockedTracks": True}), ["cuts"]),
            _plan(authority, _op("split_clips", {
                "trackIndex": 1, "frames": [24]}), ["cuts"]),
        ]
        for value in values:
            with self.subTest(tool=value["operations"][0]["tool"]):
                _reject(value, authority, "linked A/V|sync-locked|picture lane|denoise")

    def test_property_and_transform_bounds_fail_closed(self):
        authority = _authority()
        values = [
            {"clipIds": ["clip-1"], "speed": 8},
            {"clipIds": ["clip-1"], "durationFrames": 0},
            {"clipIds": ["clip-1"], "trimStartFrame": 30,
             "trimEndFrame": 20},
            {"clipIds": ["clip-1"], "transform": {"teleport": 10}},
            {"clipIds": ["clip-1"], "transform": {"centerX": 1.5}},
            {"clipIds": ["clip-1"], "transform": {
                "crop": [0.8, 0, 0.5, 1]}},
        ]
        for args in values:
            with self.subTest(args=args):
                _reject(_plan(authority, _op(
                    "set_clip_properties", args), ["cuts", "motion"]), authority)

    def test_motion_rows_require_bounds_order_and_smoothing(self):
        authority = _authority()
        rows = [
            ("scale", [[0, 1.0], [1, 1.2]]),
            ("opacity", [[0, 0], [6, 1.2]]),
            ("rotation", [[4, 0], [4, 2]]),
            ("position", [[0, [0, 0]], [5, [3, 0]]]),
        ]
        for prop, keyframes in rows:
            plan = _plan(authority, _op("set_keyframes", {
                "clipId": "clip-1", "property": prop,
                "keyframes": keyframes}), ["motion"])
            with self.subTest(prop=prop):
                _reject(plan, authority)

    def test_caption_and_text_safety_rejects_unreadable_content(self):
        authority = _authority()
        values = [
            _plan(authority, _op("add_captions", {
                "maxWords": 20, "fontSize": 64}), ["captions"]),
            _plan(authority, _op("add_captions", {
                "maxWords": 4, "fontSize": 500}), ["captions"]),
            _plan(authority, _op("add_texts", {"entries": [{
                "content": "flash", "startFrame": 10, "endFrame": 11}]}), ["graphics"]),
            _plan(authority, _op("update_text", {
                "clipIds": ["text-1"], "content": "bad\x00copy"}), ["captions"]),
            _plan(authority, _op("update_text", {
                "clipIds": ["text-1"], "transform": {"centerX": 4}}), ["captions"]),
            _plan(authority, _op("add_captions", {
                "transform": {"crop": [0.8, 0, 0.5, 1]}}), ["captions"]),
        ]
        for value in values:
            with self.subTest(tool=value["operations"][0]["tool"]):
                _reject(value, authority)

    def test_visible_text_cannot_invent_numeric_or_url_claims(self):
        authority = _authority()
        invented = _plan(authority, _op("add_texts", {"entries": [{
            "content": "10 guaranteed wins", "startFrame": 10,
            "endFrame": 30}]}), ["graphics"])
        _reject(invented, authority, "unsupported numeric")
        request = "Show five tips from the current timeline"
        supported = _plan(authority, _op("add_texts", {"entries": [{
            "content": "5 Tips", "startFrame": 10, "endFrame": 30}]}), ["graphics"])
        supported["requestHash"] = hashlib.sha256(request.encode()).hexdigest()
        self.assertEqual(validate_native_gate(
            supported, authority, request, ["graphics"]), supported)

    def test_destructive_envelope_request_hash_and_lane_binding_fail(self):
        authority = _authority()
        wipe = _plan(authority, _op("ripple_delete_ranges", {
            "clipId": "clip-1", "ranges": [[0, 120]], "units": "frames"}), ["cuts"])
        _reject(wipe, authority, "entire working timeline")
        stale = copy.deepcopy(wipe)
        stale["operations"][0]["args"]["ranges"] = [[0, 10]]
        stale["requestHash"] = "0" * 64
        _reject(stale, authority, "request hash")
        with self.assertRaisesRegex(PalmierError, "lane ownership"):
            validate_native_gate(
                _plan(authority, _op("remove_words", {"words": ["um"]}), ["cuts"]),
                authority, REQUEST, ["audio"])


if __name__ == "__main__":
    unittest.main()

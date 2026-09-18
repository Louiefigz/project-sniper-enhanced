"""Palmier canonical timeline and copy-before-AI contracts (offline only)."""
import copy
import json
import os
import tempfile
import unittest

from _common import *  # noqa: F401,F403
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import (
    TimelineConflict, candidate_path, compare_authority, fork_candidate,
    load_authority, promote_candidate, read_active, record_authority, snapshot)
from palmier.timeline_authority_cli import guard


def _timeline(timeline_id="human", clip_id="clip-1", name="Human edit"):
    return {
        "id": timeline_id, "name": name, "fps": 24, "width": 1920,
        "height": 1080, "totalFrames": 120,
        "tracks": [{"id": "track-1", "index": 0, "type": "video",
                    "clips": [{"id": clip_id, "frames": [0, 120],
                               "mediaRef": "asset-1", "opacity": 0.75,
                               "audio": {"id": f"audio-{clip_id}",
                                         "volume": 0.8}}]}],
    }


class TimelineClient:
    def __init__(self, timeline=None, project_id="project-1"):
        self.timeline = timeline or _timeline()
        self.project_id = project_id
        self.calls = []

    def call_json(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "get_projects":
            return {"projects": [{"id": self.project_id, "isActive": True}]}
        if tool == "get_timeline":
            return copy.deepcopy(self.timeline)
        if tool == "create_timeline":
            if arguments.get("from") != self.timeline["id"]:
                raise AssertionError("fork did not copy the canonical timeline")
            copied = copy.deepcopy(self.timeline)
            copied.update({"id": "candidate", "name": arguments["name"]})
            copied["tracks"][0]["id"] = "track-copy"
            copied["tracks"][0]["clips"][0]["id"] = "clip-copy"
            copied["tracks"][0]["clips"][0]["audio"]["id"] = "audio-copy"
            self.timeline = copied
            return {"timelineId": "candidate"}
        raise AssertionError(tool)


class TimelineAuthorityTests(unittest.TestCase):
    def test_hash_is_stable_but_every_exposed_content_field_matters(self):
        first = snapshot("project-1", _timeline())
        reordered = json.loads(json.dumps(_timeline(), sort_keys=True))
        self.assertEqual(first.fingerprint,
                         snapshot("project-1", reordered).fingerprint)
        changed = _timeline()
        changed["tracks"][0]["clips"][0]["opacity"] = 0.5
        self.assertNotEqual(first.fingerprint,
                            snapshot("project-1", changed).fingerprint)

    def test_runtime_state_is_ignored_but_unknown_content_is_not(self):
        offline, online = _timeline(), _timeline()
        offline["canGenerate"], online["canGenerate"] = False, True
        offline["currentFrame"], online["currentFrame"] = 0, 47
        online["timelines"] = [{"timelineId": "copy", "active": True}]
        self.assertEqual(snapshot("project-1", offline).fingerprint,
                         snapshot("project-1", online).fingerprint)
        online["futureEditProperty"] = {"strength": 0.7}
        self.assertNotEqual(snapshot("project-1", offline).fingerprint,
                            snapshot("project-1", online).fingerprint)

    def test_incomplete_large_caption_group_fails_closed(self):
        timeline = _timeline()
        timeline["tracks"].append({
            "type": "text", "clips": [],
            "captionGroups": [{"captionGroupId": "captions", "clipCount": 201}],
        })
        client = TimelineClient(timeline)
        with self.assertRaisesRegex(PalmierError, "omitted requested"):
            read_active(client, "project-1")
        self.assertTrue(any(args.get("captionDetail") is True
                            for _tool, args in client.calls))

    def test_caption_row_ids_are_copy_generated_semantic_identity(self):
        original = _timeline()
        original["tracks"].append({
            "id": "caption-track", "type": "video", "clips": [],
            "captionGroups": [{
                "captionGroupId": "group-a", "clipCount": 1,
                "clips": [["caption-a", 10, 20, "same words"]],
            }],
        })
        copied = copy.deepcopy(original)
        copied["id"], copied["name"] = "copy", "Copy"
        copied["tracks"][1]["id"] = "caption-track-copy"
        copied["tracks"][1]["captionGroups"][0]["captionGroupId"] = "group-copy"
        copied["tracks"][1]["captionGroups"][0]["clips"][0][0] = "caption-copy"
        self.assertEqual(snapshot("project-1", original).semantic_fingerprint,
                         snapshot("project-1", copied).semantic_fingerprint)

    def test_wrong_active_project_and_stale_precondition_never_fork(self):
        with self.assertRaises(TimelineConflict):
            read_active(TimelineClient(project_id="other"), "project-1")
        with tempfile.TemporaryDirectory() as tmp:
            client = TimelineClient()
            expected = record_authority(
                tmp, snapshot("project-1", _timeline()), "sniper-bootstrap")
            client.timeline["tracks"][0]["clips"][0]["frames"] = [1, 120]
            with self.assertRaisesRegex(TimelineConflict, "content-changed"):
                fork_candidate(client, tmp, expected, "AI candidate")
            self.assertNotIn("create_timeline", [name for name, _ in client.calls])

    def test_candidate_is_full_copy_but_canonical_authority_does_not_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = TimelineClient()
            expected = record_authority(
                tmp, snapshot("project-1", _timeline()), "sniper-bootstrap")
            candidate = fork_candidate(client, tmp, expected, "AI candidate")
            self.assertEqual(candidate["timelineId"], "candidate")
            self.assertEqual(candidate["status"], "staged")
            self.assertEqual(candidate["base"]["fingerprint"],
                             expected["fingerprint"])
            self.assertNotEqual(candidate["fingerprint"], expected["fingerprint"])
            self.assertEqual(candidate["semanticFingerprint"],
                             expected["semanticFingerprint"])
            self.assertEqual(load_authority(tmp), expected)
            self.assertTrue(os.path.isfile(candidate_path(tmp)))

    def test_candidate_promotion_rejects_unowned_or_legacy_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = TimelineClient()
            expected = record_authority(
                tmp, snapshot("project-1", _timeline()), "sniper-bootstrap")
            candidate = fork_candidate(client, tmp, expected, "AI candidate")
            source = snapshot("project-1", _timeline())
            with self.assertRaisesRegex(PalmierError, "controller-owned fresh proof"):
                promote_candidate(tmp, candidate)
            with self.assertRaisesRegex(PalmierError, "controller-owned fresh proof"):
                promote_candidate(tmp, {
                    "candidate": candidate, "source": source.timeline,
                    "qcApproved": True,
                })

    def test_semantic_copy_rejects_content_loss(self):
        class BrokenCopy(TimelineClient):
            def call_json(self, tool, arguments=None):
                result = super().call_json(tool, arguments)
                if tool == "create_timeline":
                    self.timeline["tracks"][0]["clips"][0]["opacity"] = 1
                return result
        with tempfile.TemporaryDirectory() as tmp:
            expected = record_authority(
                tmp, snapshot("project-1", _timeline()), "sniper-bootstrap")
            with self.assertRaisesRegex(PalmierError, "not a semantic copy"):
                fork_candidate(BrokenCopy(), tmp, expected, "AI candidate")

    def test_effect_model_id_is_content_not_a_copy_generated_identity(self):
        original = _timeline()
        original["tracks"][0]["clips"][0]["effects"] = [
            {"type": "look", "params": {"id": "look-a"}}]
        copied = copy.deepcopy(original)
        copied["id"], copied["name"] = "copy", "Copy"
        copied["tracks"][0]["id"] = "copy-track"
        copied["tracks"][0]["clips"][0]["id"] = "copy-clip"
        copied["tracks"][0]["clips"][0]["audio"]["id"] = "copy-audio"
        self.assertEqual(snapshot("project-1", original).semantic_fingerprint,
                         snapshot("project-1", copied).semantic_fingerprint)
        copied["tracks"][0]["clips"][0]["effects"][0]["params"]["id"] = "look-b"
        self.assertNotEqual(snapshot("project-1", original).semantic_fingerprint,
                            snapshot("project-1", copied).semantic_fingerprint)

    def test_manual_drift_is_adopted_but_plan_only_ai_stays_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "palmier.sync.json"), "w") as handle:
                json.dump({"projectId": "project-1"}, handle)
            initial = snapshot("project-1", _timeline())
            record_authority(tmp, initial, "sniper-bootstrap")
            client = TimelineClient()
            client.timeline["tracks"][0]["clips"][0]["frames"] = [4, 120]
            verdict = guard(client, tmp)
            self.assertFalse(verdict["ok"])
            self.assertEqual(load_authority(tmp)["origin"], "palmier-manual")
            self.assertEqual(compare_authority(load_authority(tmp),
                                               read_active(client, "project-1")),
                             "unchanged")
            self.assertFalse(guard(client, tmp)["ok"],
                             "adoption must not enable a destructive plan rewrite")


if __name__ == "__main__":
    unittest.main()
